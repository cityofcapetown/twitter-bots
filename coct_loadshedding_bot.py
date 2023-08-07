import requests

from coct_twitter_bots import utils

ARN_LOOKUP = {
    "arn:aws:sns:af-south-1:566800947500:coct-loadshedding-stage": (
    "CoCT", "stage", "https://d42sspn7yra3u.cloudfront.net/coct-load-shedding-status.json"),
    "arn:aws:sns:af-south-1:566800947500:coct-loadshedding-schedule": (
    "CoCT", "schedule", "https://d42sspn7yra3u.cloudfront.net/coct-load-shedding-extended-status.json"),
    "arn:aws:sns:af-south-1:566800947500:eskom-loadshedding-stage": (
    "Eskom", "stage", "https://d42sspn7yra3u.cloudfront.net/eskom-load-shedding-status.json"),
    "arn:aws:sns:af-south-1:566800947500:eskom-loadshedding-schedule": (
    "Eskom", "schedule", "https://d42sspn7yra3u.cloudfront.net/eskom-load-shedding-extended-status.json"),
}

DISAPPOINTMENT_SCALE = {
    0: "🙂",
    1: "😐",
    2: "😑",
    3: "😒",
    4: "😞",
    5: "😔",
    6: "😕",
    7: "😩",
    8: "😫",
    9: "🙁",
    10: "😖",
    11: "😤",
    12: "😡",
    13: "🤬",
    14: "😭",
    15: "😰",
    16: "😭😡🤬"
}

STAGE_UPDATE_TEMPLATE = """
** {provider_str} Stage Change **
Loadshedding stage is now {current_stage} {stage_emoji}!

Next up is stage {next_stage}, at {next_stage_time}.

Full schedule available at https://www.capetown.gov.za/Family%20and%20home/Residential-utility-services/Residential-electricity-services/Load-shedding-and-outages
"""

SCHEDULE_UPDATE_TEMPLATE = """
** {provider_str} Schedule Updated **
Loadshedding schedule has been updated!

Check it out at https://www.capetown.gov.za/Family%20and%20home/Residential-utility-services/Residential-electricity-services/Load-shedding-and-outages
"""


http_session = requests.Session()


def lambda_handler(event, context):
    record, *_ = event['Records']
    topic_arn = record['Sns']['TopicArn']

    provider, notification_type, data_file = ARN_LOOKUP[topic_arn]
    print(f"{provider=}, {notification_type=}, {data_file=}")

    # Creating the message text, depending on what type of message this is
    if notification_type == "stage":
        data, *_ = http_session.get(data_file).json()
        print(f"{data=}")
        current_stage = data['currentStage']
        next_stage = data['nextStage']
        next_time = data['nextStageStartTime']

        message = STAGE_UPDATE_TEMPLATE.format(provider_str=provider,
                                               current_stage=current_stage,
                                               stage_emoji=DISAPPOINTMENT_SCALE[current_stage],
                                               next_stage=next_stage,
                                               next_stage_time=next_time)

    else:
        message = SCHEDULE_UPDATE_TEMPLATE.format(provider_str=provider)

    print(f"{message=}")

    # Posting to twitter
    utils.post_tweet(message)

    return {
        'statusCode': 200,
    }
