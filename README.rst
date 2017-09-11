################
PicoPayments Hub
################

|BuildLink|_ |CoverageLink|_ |LicenseLink|_ |IssuesLink|_


.. |BuildLink| image:: https://travis-ci.org/F483/picopayments-hub.svg
.. _BuildLink: https://travis-ci.org/F483/picopayments-hub

.. |CoverageLink| image:: https://coveralls.io/repos/F483/picopayments-hub/badge.svg
.. _CoverageLink: https://coveralls.io/r/F483/picopayments-hub

.. |LicenseLink| image:: https://img.shields.io/badge/license-MIT-blue.svg
.. _LicenseLink: https://raw.githubusercontent.com/F483/picopayments-hub/master/LICENSE

.. |IssuesLink| image:: https://img.shields.io/github/issues/F483/picopayments-hub.svg
.. _IssuesLink: https://github.com/F483/picopayments-hub/issues


Decentral micropayment hub for counterparty assets.
 

==========
Node setup
==========
Currently only running on testnet,

Install IndieSqaure patched verison of counterparty with micropayment library and subasset patches
https://github.com/IndieSquare/counterparty-lib

=========
Install IndieSquare fork of picopayments hub
=========
 
```
$ git clone https://github.com/IndieSquare/picopayments-hub.git
$ cd picopayments-hub
$ sudo pip3 install -r requirements.txt
$ sudo python3 setup.py install
```
=========
Install IndieSquare fork of picopayments-cli
=========
```
$ git clone https://github.com/IndieSquare/picopayments-cli-python.git
$ cd picopayments-cli-python
$ sudo pip3 install -r requirements.txt
$ sudo python3 setup.py install
```

=========
Start hub with CP username and password
=========

```
picopayments-hub --testnet --cp_username=USERNAME --cp_password=PASSWORD --host=0.0.0.0 --cp_url=http://127.0.0.1:14000/api/
```

access from external network

curl -X POST https://your.hub.url.or.ip:15000/api/ -H 'Content-Type: application/json; charset=UTF-8' -H 'Accept: application/json, text/javascript' -k --data-binary '{ "jsonrpc": "2.0", "id": 0, "method": "mph_status" }'

=========
Common errors
=========

make sure port 15000 is open on your server

there may be possible conflicts, a common conflict may be the version of pycoin, it can be resolved via calling
```pip install pycoin==0.76```

=========
API Calls
=========

See the `API documentation <docs/api.md>`_ if you wish to create apps that interact with picopayment hubs.

