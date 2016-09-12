# coding: utf-8
# Copyright (c) 2016 Fabian Barkhau <f483@storj.io>
# License: MIT (see LICENSE file)


import os
import copy
import json
import pkg_resources
from pycoin.key.BIP32Node import BIP32Node
from pycoin.serialize import b2h, h2b
from counterpartylib.lib.micropayments import util
from counterpartylib.lib.micropayments.scripts import (
    get_deposit_payer_pubkey, get_deposit_payee_pubkey,
    get_deposit_expire_time, compile_deposit_script
)
from counterpartylib.lib.micropayments.scripts import sign_deposit
from counterpartylib.lib.micropayments.scripts import sign_finalize_commit
from counterpartylib.lib.micropayments.scripts import get_commit_payee_pubkey
from picopayments import rpc
from picopayments import db
from picopayments import auth
from picopayments import err
from picopayments import etc
from picopayments import log
from picopayments import sql


_TERMS_FP = pkg_resources.resource_stream("picopayments", "terms.json")
TERMS = json.loads(_TERMS_FP.read().decode("utf-8"))


def create_key(asset, netcode="BTC"):
    secure_random_data = os.urandom(32)
    key = BIP32Node.from_master_secret(secure_random_data, netcode=netcode)
    return {
        "asset": asset,
        "pubkey": b2h(key.sec()),
        "wif": key.wif(),
        "address": key.address(),
    }


def create_secret():
    secret = util.b2h(os.urandom(32))
    return {
        "secret_value": secret,
        "secret_hash": util.hash160hex(secret)
    }


def create_hub_connection(asset, client_pubkey, hub2client_spend_secret_hash,
                          hub_rpc_url):

    # current terms and asset
    data = {"asset": asset}
    current_terms = terms().get(asset)
    data.update(current_terms)

    # new hub key
    hub_key = create_key(asset, netcode=etc.netcode)
    data["hub_wif"] = hub_key["wif"]
    data["hub_pubkey"] = hub_key["pubkey"]
    data["hub_address"] = hub_key["address"]

    # client key
    data["client_pubkey"] = client_pubkey
    data["client_address"] = util.pubkey2address(client_pubkey,
                                                 netcode=etc.netcode)

    # spend secret for receive channel
    data.update(create_secret())

    # send micropayment channel
    data["hub2client_spend_secret_hash"] = hub2client_spend_secret_hash

    # connection
    handle = util.b2h(os.urandom(32))
    data["handle"] = handle
    data["hub_rpc_url"] = hub_rpc_url

    db.add_hub_connection(data)
    log.info("Created connection {0}".format(handle))
    return (
        {
            "handle": handle,
            "spend_secret_hash": data["secret_hash"],
            "channel_terms": current_terms
        },
        hub_key["wif"]
    )


def _load_incomplete_connection(handle, client2hub_deposit_script):

    client2hub_ds_bin = h2b(client2hub_deposit_script)
    client_pubkey = get_deposit_payer_pubkey(client2hub_ds_bin)
    hub_pubkey = get_deposit_payee_pubkey(client2hub_ds_bin)
    expire_time = get_deposit_expire_time(client2hub_ds_bin)

    hub_conn = db.hub_connection(handle=handle)
    assert(hub_conn is not None)
    assert(not hub_conn["complete"])

    hub2client = db.micropayment_channel(id=hub_conn["hub2client_channel_id"])
    assert(hub2client["payer_pubkey"] == hub_pubkey)
    assert(hub2client["payee_pubkey"] == client_pubkey)

    client2hub = db.micropayment_channel(id=hub_conn["client2hub_channel_id"])
    assert(client2hub["payer_pubkey"] == client_pubkey)
    assert(client2hub["payee_pubkey"] == hub_pubkey)

    hub_key = db.key(pubkey=hub_pubkey)

    return hub_conn, hub2client, expire_time, hub_key


def complete_connection(handle, client2hub_deposit_script,
                        next_revoke_secret_hash):

    hub_conn, hub2client, expire_time, hub_key = _load_incomplete_connection(
        handle, client2hub_deposit_script
    )

    hub2client_deposit_script = b2h(compile_deposit_script(
        hub2client["payer_pubkey"], hub2client["payee_pubkey"],
        hub2client["spend_secret_hash"], expire_time
    ))

    data = {
        "handle": handle,
        "expire_time": expire_time,
        "client2hub_channel_id": hub_conn["client2hub_channel_id"],
        "client2hub_deposit_script": client2hub_deposit_script,
        "client2hub_deposit_address": util.script2address(
            h2b(client2hub_deposit_script), netcode=etc.netcode
        ),
        "hub2client_channel_id": hub_conn["hub2client_channel_id"],
        "hub2client_deposit_script": hub2client_deposit_script,
        "hub2client_deposit_address": util.script2address(
            h2b(hub2client_deposit_script), netcode=etc.netcode
        ),
        "next_revoke_secret_hash": next_revoke_secret_hash,
    }

    data.update(create_secret())  # revoke secret

    db.complete_hub_connection(data)
    log.info("Completed connection {0}".format(handle))
    return (
        {
            "deposit_script": hub2client_deposit_script,
            "next_revoke_secret_hash": data["secret_hash"]
        },
        hub_key["wif"]
    )


def find_key_with_funds(asset, asset_quantity, btc_quantity):
    btc_quantity = btc_quantity + util.get_fee_multaple(
        factor=1, fee_per_kb=etc.fee_per_kb,
        regular_dust_size=etc.regular_dust_size
    )
    nearest = {"key": None, "available": 2100000000000000}
    for key in db.keys(asset=asset):
        address = key["address"]
        if has_unconfirmed_transactions(address):
            continue  # ignore if unconfirmed inputs/outputs
        available = balance(address, asset)
        # FIXME check btc quantity
        if available < asset_quantity:
            continue  # not enough funds
        if nearest["available"] > available:
            nearest = {"key": key, "available": available}
    return nearest["key"]


def get_funding_addresses(assets):
    addresses = {}
    for asset in assets:
        key = create_key(asset, netcode=etc.netcode)
        db.add_keys([key])
        addresses[asset] = key["address"]
    return addresses


def initialize(args):
    etc.load(args)  # load configuration

    # ensure basedir path exists
    if not os.path.exists(etc.basedir):
        os.makedirs(etc.basedir)

    terms()  # make sure terms file exists
    db.setup()  # setup and create db if needed
    log.info("Basedir: {0}".format(etc.basedir))  # make sure log file exists


def update_channel_state(channel_id, asset, commit=None,
                         revokes=None, cursor=None):

    state = db.load_channel_state(channel_id, asset, cursor=cursor)
    unnotified_revokes = db.unnotified_revokes(channel_id=channel_id)
    unnotified_commit = db.unnotified_commit(channel_id=channel_id,
                                             cursor=cursor)
    if commit is not None:
        state = rpc.cp_call(
            method="mpc_add_commit",
            params={
                "state": state,
                "commit_rawtx": commit["rawtx"],
                "commit_script": commit["script"]
            }
        )
    if revokes is not None:
        state = rpc.cp_call(
            method="mpc_revoke_all",
            params={
                "state": state, "secrets": revokes
            }
        )
    db.save_channel_state(
        channel_id, state, unnotified_commit=unnotified_commit,
        unnotified_revokes=unnotified_revokes, cursor=cursor
    )
    return state


def _save_sync_data(cursor, handle, next_revoke_secret_hash,
                    receive_payments, hub2client_commit_id, hub2client_revokes,
                    client2hub_id, next_revoke_secret):

    cursor.execute("BEGIN TRANSACTION;")

    # set next revoke secret hash from client
    db.set_next_revoke_secret_hash(handle, next_revoke_secret_hash)

    # mark sent payments as received
    payment_ids = [{"id": p.pop("id")} for p in receive_payments]
    db.set_payments_notified(payment_ids, cursor=cursor)

    # mark sent commit as received
    if hub2client_commit_id:
        db.set_commit_notified(id=hub2client_commit_id, cursor=cursor)

    # mark sent revokes as received
    revoke_ids = [p.pop("id") for p in hub2client_revokes]
    db.set_revokes_notified(revoke_ids, cursor=cursor)

    # save next spend secret
    db.add_revoke_secret(client2hub_id, next_revoke_secret["secret_hash"],
                         next_revoke_secret["secret_value"], cursor=cursor)

    cursor.execute("COMMIT;")


def sync_hub_connection(handle, next_revoke_secret_hash,
                        sends, commit, revokes):

    cursor = sql.get_cursor()

    # load receive channel
    hub_connection = db.hub_connection(handle=handle, cursor=cursor)
    connection_terms = db.terms(id=hub_connection["terms_id"])
    asset = hub_connection["asset"]
    client2hub_id = hub_connection["client2hub_channel_id"]
    hub2client_id = hub_connection["hub2client_channel_id"]

    # update channels state
    update_channel_state(client2hub_id, asset, commit=commit, cursor=cursor)
    update_channel_state(hub2client_id, asset, revokes=revokes, cursor=cursor)

    # add sync fee payment
    sends.insert(0, {
        "payee_handle": None,  # to hub
        "amount": connection_terms["sync_fee"],
        "token": "sync_fee"
    })

    # process payments
    for payment in sends:
        process_payment(handle, cursor, payment)

    # create next spend secret
    next_revoke_secret = create_secret()

    # load unnotified
    hub2client_commit = db.unnotified_commit(channel_id=hub2client_id)
    hub2client_revokes = db.unnotified_revokes(channel_id=hub2client_id)
    receive_payments = db.unnotified_payments(payee_handle=handle)

    # save sync data
    hub2client_commit_id = None
    if hub2client_commit:
        hub2client_commit_id = hub2client_commit.pop("id")
    _save_sync_data(
        cursor, handle, next_revoke_secret_hash, receive_payments,
        hub2client_commit_id, hub2client_revokes, client2hub_id,
        next_revoke_secret
    )

    hub_key = db.channel_payer_key(id=hub2client_id)
    return (
        {
            "receive": receive_payments,
            "commit": hub2client_commit,
            "revokes": [r["revoke_secret"] for r in hub2client_revokes],
            "next_revoke_secret_hash": next_revoke_secret["secret_hash"]
        },
        hub_key["wif"]
    )


def balance(address, asset):
    results = rpc.cp_call(
        method="get_balances",
        params={
            "filters": [
                {'field': 'address', 'op': '==', 'value': address},
                {'field': 'asset', 'op': '==', 'value': asset},
            ]
        }
    )
    return results[0]["quantity"] if results else 0


def deposit_address(state):
    return get_script_address(state["deposit_script"])


def get_script_address(script):
    return util.script2address(util.h2b(script), netcode=etc.netcode)


def transferred(state):
    return rpc.cp_call(
        method="mpc_transferred_amount",
        params={"state": state}
    )


def expired(state, clearance):
    return rpc.cp_call(
        method="mpc_deposit_expired",
        params={"state": state, "clearance": clearance}
    )


def get_tx(txid):
    return rpc.cp_call(method="getrawtransaction", params={"tx_hash": txid})


def publish(rawtx, publish_tx=True):
    if not publish_tx:
        return util.gettxid(rawtx)
    return rpc.cp_call(
        method="sendrawtransaction", params={"tx_hex": rawtx}
    )  # pragma: no cover


def publish_highest_commit(state, publish_tx=True):
    commit = rpc.cp_call(method="mpc_highest_commit", params={"state": state})
    if commit is None:
        return None
    script = util.h2b(commit["script"])
    rawtx = commit["rawtx"]
    pubkey = get_commit_payee_pubkey(script)
    key = db.key(pubkey=util.b2h(pubkey))
    signed_rawtx = sign_finalize_commit(get_tx, key["wif"], rawtx, script)
    return publish(signed_rawtx, publish_tx=publish_tx)


def send(destination, asset, quantity, publish_tx=True):
    extra_btc = util.get_fee_multaple(
        factor=3, fee_per_kb=etc.fee_per_kb,
        regular_dust_size=etc.regular_dust_size
    )
    key = find_key_with_funds(asset, quantity, extra_btc)
    if key is None:
        raise err.InsufficientFunds(asset, quantity)
    unsigned_rawtx = rpc.cp_call(
        method="create_send",
        params={
            "source": key["address"],
            "destination": destination,
            "asset": asset,
            "regular_dust_size": extra_btc,
            "disable_utxo_locks": True,
            "quantity": quantity
        }
    )
    signed_rawtx = sign_deposit(get_tx, key["wif"], unsigned_rawtx)
    return publish(signed_rawtx, publish_tx=publish_tx)


def get_transactions(address):
    return rpc.cp_call(
        method="search_raw_transactions",
        params={"address": address, "unconfirmed": True}
    )


def commit_published(state):
    # FIXME this should be a counterpartylib call mpc_is_commit_published
    deposit_transactions = get_transactions(deposit_address(state))
    deposit_txids = [tx["txid"] for tx in deposit_transactions]
    commits = state["commits_active"] + state["commits_revoked"]
    commit_scripts = [commit["script"] for commit in commits]
    commit_addresses = [get_script_address(s) for s in commit_scripts]
    for commit_address in commit_addresses:
        for commit_transaction in get_transactions(commit_address):
            txid = commit_transaction["txid"]
            if txid in deposit_txids:
                return txid  # spend from deposit -> commit
    return None


def has_unconfirmed_transactions(address):
    transactions = get_transactions(address)
    for transaction in transactions:
        if transaction.get("confirmations", 0) == 0:
            return True
    return False


def load_connection_data(handle, cursor):
    connection = db.hub_connection(handle=handle, cursor=cursor)
    terms = db.terms(id=connection["terms_id"], cursor=cursor)
    hub2client_state = db.load_channel_state(
        connection["hub2client_channel_id"], connection["asset"], cursor=cursor
    )
    hub2client_deposit_address = deposit_address(hub2client_state)
    client2hub_state = db.load_channel_state(
        connection["client2hub_channel_id"], connection["asset"], cursor=cursor
    )
    client2hub_deposit_address = deposit_address(client2hub_state)
    hub2client_transferred = transferred(hub2client_state)
    hub2client_deposit_amount = balance(hub2client_deposit_address,
                                        connection["asset"])
    client2hub_transferred = transferred(client2hub_state)
    client2hub_deposit_amount = balance(client2hub_deposit_address,
                                        connection["asset"])
    unnotified_commit = db.unnotified_commit(
        channel_id=connection["hub2client_channel_id"], cursor=cursor
    )
    hub2client_payments_sum = db.hub2client_payments_sum(handle=handle,
                                                         cursor=cursor)
    client2hub_payments_sum = db.client2hub_payments_sum(handle=handle,
                                                         cursor=cursor)
    transferred_amount = client2hub_transferred - hub2client_transferred
    payments_sum = hub2client_payments_sum - client2hub_payments_sum

    # sendable (what this channel can send to another)
    sendable_amount = transferred_amount - payments_sum

    # receivable (what this channel can receive from another)
    receivable_potential = hub2client_deposit_amount + client2hub_transferred
    receivable_owed = (abs(payments_sum) if payments_sum < 0 else 0)
    receivable_amount = receivable_potential - receivable_owed

    return {
        "connection": connection,
        "hub2client_state": hub2client_state,
        "hub2client_expired": expired(hub2client_state, etc.expire_clearance),
        "hub2client_transferred_amount": hub2client_transferred,
        "hub2client_payments_sum": hub2client_payments_sum,
        "hub2client_deposit_amount": hub2client_deposit_amount,
        "client2hub_state": client2hub_state,
        "client2hub_expired": expired(client2hub_state, etc.expire_clearance),
        "client2hub_transferred_amount": client2hub_transferred,
        "client2hub_payments_sum": client2hub_payments_sum,
        "client2hub_deposit_amount": client2hub_deposit_amount,
        "transferred_amount": transferred_amount,
        "payments_sum": payments_sum,
        "unnotified_commit": unnotified_commit,
        "sendable_amount": sendable_amount,
        "receivable_amount": receivable_amount,
        "terms": terms,
    }


def process_payment(payer_handle, cursor, payment):

    # load payer
    payer = load_connection_data(payer_handle, cursor)

    # check if connection expired
    if payer["client2hub_expired"]:
        raise err.DepositExpired(payer_handle, "client")
    if payer["hub2client_expired"]:
        raise err.DepositExpired(payer_handle, "hub")  # pragma: no cover

    # check payer has enough funds or can revoke sends until enough available
    if payment["amount"] > payer["sendable_amount"]:
        raise err.PaymentExceedsSpendable(
            payment["amount"], payer["sendable_amount"], payment["token"]
        )

    # load payee
    payee_handle = payment["payee_handle"]
    if payee_handle:
        payee = load_connection_data(payee_handle, cursor)
        if payer["connection"]["asset"] != payee["connection"]["asset"]:
            raise err.AssetMissmatch(
                payer["connection"]["asset"], payee["connection"]["asset"]
            )

        # check if connection expired
        if payee["hub2client_expired"]:
            raise err.DepositExpired(payee_handle, "hub")
        if payee["client2hub_expired"]:
            raise err.DepositExpired(
                payee_handle, "client")  # pragma: no cover

        if payment["amount"] > payee["receivable_amount"]:
            raise err.PaymentExceedsReceivable(
                payment["amount"], payee["receivable_amount"], payment["token"]
            )
        cursor.execute("BEGIN TRANSACTION;")

        # FIXME adjust payee channel

    # fee payment
    else:
        cursor.execute("BEGIN TRANSACTION;")

    payment["payer_handle"] = payer_handle
    db.add_payment(cursor=cursor, **payment)
    cursor.execute("COMMIT;")


def terms(assets=None):

    # create terms and return default value
    if not os.path.exists(etc.path_terms):
        default_terms = TERMS["TESTNET"] if etc.testnet else TERMS["MAINNET"]
        with open(etc.path_terms, 'w') as outfile:
            json.dump(default_terms, outfile, indent=2)
        terms_data = copy.deepcopy(default_terms)

    # read terms
    else:
        with open(etc.path_terms, 'r') as infile:
            terms_data = json.load(infile)

    # FIXME validate terms data

    # limit to given assets
    if assets:
        for key in list(terms_data.keys())[:]:
            if key not in assets:
                terms_data.pop(key)

    return terms_data


def hub_connections(handles, assets):
    connections = []
    for connection in db.hub_connections():
        if assets is not None and connection["asset"] not in assets:
            continue
        if handles is not None and connection["handle"] not in handles:
            continue
        wif = connection.pop("wif")
        connection = auth.sign_json(connection, wif)
        connections.append(connection)
    return connections