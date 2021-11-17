import argparse
import glob
import json
import os
import re

import rlog
import solcx
from decouple import config
from web3 import Web3
from web3.middleware import geth_poa_middleware


def _get_contract_names(src_dir):
    """get all solidity contract names present in src_dir"""
    names = []
    for srcfile in glob.glob(f"{src_dir}/*.sol"):
        with open(srcfile, "r") as f:
            srccode = f.read()
            m = re.search(r"contract (\w+) is", srccode)
            names.append(m.group(1))

    return names


def deploy():
    # check for help flag
    parser = argparse.ArgumentParser(description="deploy solidity contracts through json-rpc")
    parser.add_argument("--envdesc", action="store_true")
    parser.add_argument("--env", action="store_true")
    args = parser.parse_args()
    if args.envdesc:
        print(
            "WEB3_SOL_SRCDIR: dir containing solidity contract files (src/sol)\n"
            "WEB3_SOLC_VER: desired solc compiler version (0.8.9)\n"
            "WEB3_BUILD_DIR: destination dir for build artifacts (./build/web3deploy)\n"
            "WEB3_HTTP_PROVIDER: host/port for eth client json-rpc interface (http://localhost:8545)\n"
            "WEB3_POA: enable proof-of-authority metadata (True)\n"
            "WEB3_KEY_INDEX: account index to use from provider (0)\n"
        )
        return
    if args.env:
        print(
            "WEB3_SOL_SRCDIR=src/sol\n"
            "WEB3_SOLC_VER=0.8.9\n"
            "WEB3_BUILD_DIR=build/web3deploy\n"
            "WEB3_HTTP_PROVIDER=http://localhost:8545\n"
            "WEB3_POA=True\n"
            "WEB3_KEY_INDEX=0\n"
        )
        return

    # locate contract files in package directory
    sol_src_dir = config("WEB3_SOL_SRCDIR", default="src/sol")
    contract_files = glob.glob(f"{sol_src_dir}/*.sol")

    # compile contract files
    remappings = {
        "@openzeppelin": "node_modules/@openzeppelin",
        "@chainlink": "node_modules/@chainlink",
    }
    compiled_contracts = solcx.compile_files(
        contract_files,
        import_remappings=remappings,
        solc_version=config("WEB3_SOLC_VER", default="0.8.9"),
        base_path=os.getcwd(),
        allow_paths=os.getcwd(),
    )

    # write output abi to build files
    contract_dir = f"{config('WEB3_BUILD_DIR', default='build/web3deploy')}/contract"
    if not os.path.exists(contract_dir):
        os.makedirs(contract_dir)
    with open(f"{contract_dir}/compile.json", "w") as f:
        json.dump(compiled_contracts, f)

    # deploy contract across web3
    w3 = Web3(Web3.HTTPProvider(config("WEB3_HTTP_PROVIDER", default="http://localhost:8545")))

    if config("WEB3_POA", default=False):
        rlog.info("Injecting geth_poa_middleware")
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    w3.eth.default_account = w3.eth.accounts[config("WEB3_KEY_INDEX", cast=int, default=0)]

    address_dct = {}
    for contract_id, contract_interface in compiled_contracts.items():
        contract_name = contract_id.split(":")[-1]
        if contract_name in _get_contract_names(sol_src_dir):
            contract = w3.eth.contract(
                abi=contract_interface["abi"], bytecode=contract_interface["bin"]
            )
            tx_hash = contract.constructor().transact()
            tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            address_dct[contract_name] = tx_receipt.contractAddress
            rlog.info(f"contract: {tx_receipt.contractAddress}")

    # save contract deploy data to disk
    with open(f"{contract_dir}/deploy.json", "w") as f:
        json.dump(address_dct, f)
