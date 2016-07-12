# coding: utf-8
# Copyright (c) 2016 Fabian Barkhau <fabian.barkhau@gmail.com>
# License: MIT (see LICENSE file)


import os
import json
from . import cfg


DEFAULT_MAINNET = {
    "BTC": {
        "setup_ttl": 2,  # blocks,
        "deposit_limit": 0,  # satoshis,
        "deposit_ratio": 1.0,  # float,
        "timeout_limit": 0,  # blocks,
        "fee_setup": 10,  # satoshis,
        "fee_sync": 1,  # satoshis
    },
    "XCP": {
        "setup_ttl": 2,  # blocks,
        "deposit_limit": 0,  # satoshis,
        "deposit_ratio": 1.0,  # float,
        "timeout_limit": 0,  # blocks,
        "fee_setup": 10,  # satoshis,
        "fee_sync": 1,  # satoshis
    },
    "SJCX": {
        "setup_ttl": 2,  # blocks,
        "deposit_limit": 0,  # satoshis,
        "deposit_ratio": 1.0,  # float,
        "timeout_limit": 0,  # blocks,
        "fee_setup": 10,  # satoshis,
        "fee_sync": 1,  # satoshis
    },
}


DEFAULT_TESTNET = {
    "BTC": {
        "setup_ttl": 2,  # blocks,
        "deposit_limit": 0,  # satoshis,
        "deposit_ratio": 1.0,  # float,
        "timeout_limit": 0,  # blocks,
        "fee_setup": 10,  # satoshis,
        "fee_sync": 1,  # satoshis
    },
    "XCP": {
        "setup_ttl": 2,  # blocks,
        "deposit_limit": 0,  # satoshis,
        "deposit_ratio": 1.0,  # float,
        "timeout_limit": 0,  # blocks,
        "fee_setup": 10,  # satoshis,
        "fee_sync": 1,  # satoshis
    },
    "A14456548018133352000": {
        "setup_ttl": 2,  # blocks,
        "deposit_limit": 0,  # satoshis,
        "deposit_ratio": 1.0,  # float,
        "timeout_limit": 0,  # blocks,
        "fee_setup": 10,  # satoshis,
        "fee_sync": 1,  # satoshis
    },
}


def read(asset):
    terms_file = cfg.testnet_terms if cfg.testnet else cfg.mainnet_terms
    terms_path = os.path.join(cfg.root, terms_file)

    # create terms and return default value
    if not os.path.exists(terms_path):

        # ensure root path exists
        if not os.path.exists(os.path.dirname(terms_path)):
            os.makedirs(os.path.dirname(terms_path))

        default_terms = DEFAULT_TESTNET if cfg.testnet else DEFAULT_MAINNET
        with open(terms_path, 'w') as outfile:
            json.dump(default_terms, outfile, indent=2)
        return default_terms.get(asset)

    # read terms
    else:
        with open(terms_path, 'r') as infile:
            terms = json.load(infile)
            return terms.get(asset)