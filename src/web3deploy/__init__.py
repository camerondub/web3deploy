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


def _get_contract_name(srcfile):
    """get singular contract name in singular solidity src file"""
    with open(srcfile, "r") as f:
        srccode = f.read()
        m = re.search(r"contract (\w[\w\d]+) (is|\{)", srccode)
        if m:
            return m.group(1)
        else:
            raise KeyError("contract name regex unmatched")


def _get_contract_names(files):
    """get all solidity contract names present in files list"""
    return [_get_contract_name(srcfile) for srcfile in files]


def deploy():
    # check for help flag
    parser = argparse.ArgumentParser(description="deploy solidity contracts through json-rpc")
    parser.add_argument("--envdesc", "-d", action="store_true")
    parser.add_argument("--env", "-e", action="store_true")
    parser.add_argument("--files", "-f", nargs="*")
    parser.add_argument("--optimize", "-o", nargs="?", type=int, default=0, const=200)
    args = parser.parse_args()
    if args.envdesc:
        print(
            "WEB3_SOL_SRCDIR: dir containing solidity contract files (src/sol)\n"
            "WEB3_SOLC_VER: desired solc compiler version (0.8.9)\n"
            "WEB3_BUILD_DIR: destination dir for build artifacts (./build/web3deploy)\n"
            "WEB3_HTTP_PROVIDER: url for eth client json-rpc interface (http://localhost:8545)\n"
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
    if args.files:
        contract_files = args.files
    else:
        contract_files = glob.glob(f"{sol_src_dir}/*.sol")

    rlog.info(f"{contract_files =}")

    # compile contract files
    remappings = {
        "@openzeppelin": "node_modules/@openzeppelin",
        "@chainlink": "node_modules/@chainlink",
    }
    compiler_ver = config("WEB3_SOLC_VER", default="0.8.9")
    rlog.info(f"optimize={bool(args.optimize)}, runs={args.optimize} {compiler_ver=}")
    if args.optimize:
        optimize_kwargs = {"optimize": bool(args.optimize), "optimize_runs": args.optimize}
    else:
        optimize_kwargs = {}
    compiled_contracts = solcx.compile_files(
        contract_files,
        import_remappings=remappings,
        solc_version=compiler_ver,
        base_path=os.getcwd(),
        allow_paths=os.getcwd(),
        **optimize_kwargs,
    )

    # write output abi to build files
    build_dir = config("WEB3_BUILD_DIR", default="build/web3deploy")
    contract_dir = f"{build_dir}/contract"
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
    local_contract_names = _get_contract_names(contract_files)
    for contract_id, contract_interface in compiled_contracts.items():
        contract_name = contract_id.split(":")[-1]
        if contract_name in local_contract_names:
            contract = w3.eth.contract(
                abi=contract_interface["abi"], bytecode=contract_interface["bin"]
            )
            tx_hash = contract.constructor().transact()
            tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            address_dct[contract_name] = tx_receipt.contractAddress
            rlog.info(f"contract {contract_name}: {tx_receipt.contractAddress}")

    # read existing address data into memory
    try:
        with open(f"{build_dir}/address.json", "r") as f:
            old_address_dct = json.load(f)
    except FileNotFoundError as e:
        rlog.warning(f"address.json not found: {e}")

    # TODO: merge old_address_dct into address_dct

    # save contract deploy data to disk
    with open(f"{build_dir}/deploy.json", "w") as f:
        json.dump(address_dct, f)
