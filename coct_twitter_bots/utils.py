import contextlib
import os

import requests.models
from requests_oauthlib import OAuth1Session


@contextlib.contextmanager
def init_twitter_oauth_session() -> OAuth1Session:
    # borrowed heavily from
    # https://github.com/twitterdev/Twitter-API-v2-sample-code/blob/main/Manage-Tweets/create_tweet.py
    with OAuth1Session(os.environ["TWITTER_CONSUMER_KEY"],
                       client_secret=os.environ["TWITTER_CONSUMER_SECRET"],
                       resource_owner_key=os.environ["TWITTER_ACCESS_TOKEN"],
                       resource_owner_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"]) as oauth_session:
        yield oauth_session


def post_tweet(text: str) -> requests.models.Response:
    with init_twitter_oauth_session() as oauth:
        response = oauth.post(
            "https://api.twitter.com/2/tweets",
            json={"text": text},
        )

        assert response.status_code == 201, f"Response not 201, is {response.status_code}: {response.text}"

        return response


TWEET_MAX_LENGTH = 280

TWITTER_BOT_BUCKET = "coct-twitter-bot"
