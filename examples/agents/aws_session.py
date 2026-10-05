"""A small adapter: every client is created directly by botocore."""
import botocore.session


class AwsSession:
    def __init__(self, region_name=None):
        self.session = botocore.session.get_session()
        self.region = region_name

    def client(self, service, **kwargs):
        return self.session.create_client(service, region_name=self.region, **kwargs)

    def get_credentials(self):
        return self.session.get_credentials()
