import os
import json
import shutil
import unittest
import tempfile
from picopayments import srv
from picopayments import rpc
from picopayments import Client


rpc.CALL_LOCAL_PROCESS = True
CP_URL = "http://139.59.214.74:14000/api/"


class TestUsrClientConnect(unittest.TestCase):

    # FIXME test fails if request made, deposit not made then sync

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="picopayments_test_")
        self.basedir = os.path.join(self.tempdir, "basedir")
        shutil.copytree("tests/fixtures", self.basedir)
        srv.main([
            "--testnet",
            "--basedir={0}".format(self.basedir),
            "--cp_url={0}".format(CP_URL)
        ], serve=False)
        with open(os.path.join(self.basedir, "data.json")) as fp:
            self.data = json.load(fp)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_standard_usage(self):
        verify_ssl_cert = False
        auth_wif = self.data["funded"]["alpha"]["wif"]
        asset = self.data["funded"]["alpha"]["asset"]
        client = Client(auth_wif=auth_wif, verify_ssl_cert=verify_ssl_cert)
        txid = client.connect(1337, 65535, asset=asset, publish_tx=False)
        self.assertIsNotNone(txid)


if __name__ == "__main__":
    unittest.main()
