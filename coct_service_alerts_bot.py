from datetime import datetime, timedelta
import json

import boto3
import openai

from coct_twitter_bots.utils import post_tweet, TWEET_MAX_LENGTH, TWITTER_BOT_BUCKET

SERVICE_ALERT_PREFIX = "alerts"

CHATGPT_TEMPLATE = """
Please draft a tweet about a potential City of Cape Town service outage or update, using any of the details in the 
following JSON. The "service_area" field refers to the responsible department.

{json_str}

Please end with the sentence '{link_str}' on its own line.

Only return the content of the post and keep it under 280 characters - you don't have to mention all of the details.
"""

REQUEST_RETRIES = 3
REQUEST_TIMEOUT = 60

LINK_TEMPLATE = "Generated automatically using https://d1mqopqocx2rjl.cloudfront.net/{prefix_str}/{service_alert_filename}"

s3 = boto3.client('s3')


def _convert_to_sast_str(utc_str: str) -> str:
    return (
            datetime.strptime(utc_str[:-5], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=2)
    ).strftime("%Y-%m-%dT%H:%M:%S") + "+02:00"


def _chatgpt_wrapper(message: str) -> str:
    rough_token_count = len(message) // 4 + 256
    temperature = 0.2

    last_error = None
    for t in range(REQUEST_RETRIES):
        response_message = None
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": message},
                ],
                temperature=temperature,
                max_tokens=4097 - rough_token_count,
                timeout=REQUEST_TIMEOUT
            )
            response_message = response['choices'][0]['message']['content']

            # Checking response length is right
            assert len(response_message) <= TWEET_MAX_LENGTH, "message is too long!"

            return response_message

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


def lambda_handler(event, context):
    record, *_ = event['Records']
    sns_message = record['Sns']['Message']
    data = json.loads(sns_message)
    print(f"{len(data)=}")

    for service_alert in data:
        service_alert_id = service_alert['Id']
        service_alert_filename = f"{service_alert_id}.json"

        # Removing a few fields which often confuse ChatGPT
        for field in ('Id', 'publish_date', 'effective_date', 'expiry_date'):
            del service_alert[field]

        # Also, removing any null items
        keys_to_delete = [
            k for k, v in service_alert.items()
            if v is None
        ]

        for k in keys_to_delete:
            del service_alert[k]

        # converting the timezone values to SAST
        for ts in ("start_timestamp", "forecast_end_timestamp"):
            service_alert[ts] = _convert_to_sast_str(service_alert[ts])

        # Forming content
        link_str = LINK_TEMPLATE.format(prefix_str=SERVICE_ALERT_PREFIX,
                                        service_alert_filename=service_alert_filename)

        # Trying to get text from ChatGPT
        try:
            gpt_template = CHATGPT_TEMPLATE.format(json_str=json.dumps(service_alert),
                                                   link_str=link_str)
            gpt_template += (
                " . Encourage the use of the request_number value when contacting the City"
                if "request_number" in service_alert else ""
            )

            # Getting tweet text from ChatGPT
            message = _chatgpt_wrapper(gpt_template)

        except Exception as e:
            # Failing with a sensible message
            print(f"Failed to generate tweet text for '{service_alert_id}' because {e.__class__.__name__}")
            message = f"Failed to generate content. Please consult link below.\n{link_str}"

        # Backing up source data and tweet to S3
        service_alert["tweet"] = message
        service_alert_json = json.dumps(service_alert)

        s3.put_object(
            Body=service_alert_json,
            Bucket=TWITTER_BOT_BUCKET,
            Key=SERVICE_ALERT_PREFIX + "/" + service_alert_filename,
            ContentType='application/json'
        )

        # All done, posting to Twitter
        post_tweet(message)

    return {
        'statusCode': 200,
    }
