import argparse
import glob
import json
import os

import rlog
import solcx
from decouple import config
from web3 import Web3
from web3.middleware import geth_poa_middleware


def main():
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
        solc_version=config("WEB3_SOLC_VER", default="0.8.10"),
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
    w3 = Web3(Web3.HTTPProvider(config("WEB3_HTTP_PROVIDER")))

    if config("WEB3_POA", default=False):
        rlog.info("Injecting geth_poa_middleware")
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    w3.eth.default_account = w3.eth.accounts[config("WEB3_KEY_INDEX", cast=int)]

    address_dct = {}
    for contract_id, contract_interface in compiled_contracts.items():
        contract_name = contract_id.split(":")[-1]
        if contract_name == config("WEB3_CONTRACT_NAME"):
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
