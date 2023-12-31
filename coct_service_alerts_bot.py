from datetime import datetime, timedelta
import json
import typing

import boto3
import openai
import requests

from coct_twitter_bots.utils import post_tweet, TWEET_MAX_LENGTH, TWITTER_BOT_BUCKET

SERVICE_ALERT_PREFIX = "alerts"

CHATGPT_TEMPLATE = """
Please draft a tweet about a potential City of Cape Town service outage or update, using any of the details in the 
following JSON. The "service_area" field refers to the responsible department. Please prioritise the location and time
information.

{json_str}

Please end with the sentence '{link_str}' on its own line.

Only return the content of the post and keep it under 260 characters - you don't have to mention all of the details.
"""

TRY_AGAIN_TEMPLATE = """
This tweet is too long, please shorten it to 250 characters or less:

{tweet_str}

Please still mention it has been autogenerated and the link to the source data.
"""

REQUEST_RETRIES = 3
REQUEST_TIMEOUT = 60

LINK_TEMPLATE = "**Autogenerated** using https://d1mqopqocx2rjl.cloudfront.net/{prefix_str}/{service_alert_filename}"

ALERTS_TEMPLATE = "https://service-alerts.cct-datascience.xyz/alerts/{alert_id}.json"

s3 = boto3.client('s3')
http_session = requests.Session()

def _convert_to_sast_str(utc_str: str) -> str:
    return (
            datetime.strptime(utc_str[:-5], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=2)
    ).strftime("%Y-%m-%dT%H:%M:%S") + "+02:00"


def _chatgpt_wrapper(message: str) -> str:
    gpt_message = message
    rough_token_count = len(gpt_message) // 4 + 256
    temperature = 0.2

    last_error = None
    for t in range(REQUEST_RETRIES):
        response_message = None
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": gpt_message},
                ],
                temperature=temperature,
                max_tokens=4097 - rough_token_count,
                timeout=REQUEST_TIMEOUT
            )
            response_message = response['choices'][0]['message']['content']

            # Checking response length is right
            assert len(response_message) <= TWEET_MAX_LENGTH, "message is too long!"

            return response_message

        except AssertionError as e:
            print("Tweet too long - trying to get GPT to shorten it...")
            print(f"try: {t + 1}/3")
            print(f"{response_message=}")

            gpt_message = TRY_AGAIN_TEMPLATE.format(
                tweet_str=response_message
            )
            rough_token_count = len(gpt_message) // 4 + 256
            temperature += 0.2

            last_error = e

        except Exception as e:
            print(f"Got {e.__class__.__name__}: {e}")
            print(f"try: {t + 1}/3")
            print(f"{response_message=}")

            if isinstance(e, openai.error.InvalidRequestError):
                print("increasing token count")
                rough_token_count *= 1.2
                rough_token_count = int(rough_token_count)
            else:
                temperature += 0.2

            last_error = e
    else:
        raise last_error


def _generate_tweet_from_chatgpt(alert: typing.Dict, alert_id: str, alert_filename: str) -> str:
    # Removing a few fields which often confuse ChatGPT
    for field in ('Id', 'publish_date', 'effective_date', 'expiry_date'):
        del alert[field]

    # Also, removing any null items
    keys_to_delete = [
        k for k, v in alert.items()
        if v is None
    ]

    for k in keys_to_delete:
        del alert[k]

    # converting the timezone values to SAST
    for ts in ("start_timestamp", "forecast_end_timestamp"):
        alert[ts] = _convert_to_sast_str(alert[ts])

    # Forming content
    link_str = LINK_TEMPLATE.format(prefix_str=SERVICE_ALERT_PREFIX,
                                    service_alert_filename=alert_filename)

    # Trying to get text from ChatGPT
    try:
        gpt_template = CHATGPT_TEMPLATE.format(json_str=json.dumps(alert),
                                               link_str=link_str)
        gpt_template += (
            " . Encourage the use of the request_number value when contacting the City"
            if "request_number" in alert else ""
        )

        # Getting tweet text from ChatGPT
        message = _chatgpt_wrapper(gpt_template)

    except Exception as e:
        # Failing with a sensible message
        print(f"Failed to generate tweet text for '{alert_id}' because {e.__class__.__name__}")
        message = f"Failed to generate content. Please consult link below.\n{link_str}"

    return message


def lambda_handler(event, context):
    record, *_ = event['Records']
    sns_message = record['Sns']['Message']
    data = json.loads(sns_message)
    print(f"{len(data)=}")

    for service_alert in data:
        service_alert_id = service_alert['Id']
        service_alert_filename = f"{service_alert_id}.json"
        service_alert_key = SERVICE_ALERT_PREFIX + "/" + service_alert_filename

        list_response = s3.list_objects_v2(Bucket=TWITTER_BOT_BUCKET, Prefix=service_alert_key)

        if 'Contents' in list_response:
            print(f"{service_alert_id} already exists, skipping!")
            continue

        message = None

        # try load message from v1 endpoint
        service_alert_path = ALERTS_TEMPLATE.format(alert_id=service_alert_id)
        if requests.head(service_alert_path).status_code == 200:
            service_alert_data = http_session.get(service_alert_path).json()
            message = service_alert_data.get("tweet_text", None)
            if message:
                print("Using cptgpt text")

        # failing v1 endpoint, fall back to chatgpt
        if message is None:
            message = _generate_tweet_from_chatgpt(service_alert, service_alert_id, service_alert_filename)

        # Backing up source data and tweet to S3
        service_alert["tweet_text"] = message
        service_alert_json = json.dumps(service_alert)

        s3.put_object(
            Body=service_alert_json,
            Bucket=TWITTER_BOT_BUCKET,
            Key=service_alert_key,
            ContentType='application/json'
        )

        # All done, posting to Twitter
        post_tweet(message)

    return {
        'statusCode': 200,
    }
