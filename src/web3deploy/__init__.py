import argparse
import glob
import json
import os
import re
import sys

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


def _parse_cmdline():
    # check for help flag
    parser = argparse.ArgumentParser(description="deploy solidity contracts through json-rpc")
    parser.add_argument("--clear", "-c", action="store_true")
    parser.add_argument("--envdesc", "-d", action="store_true")
    parser.add_argument("--env", "-e", action="store_true")
    parser.add_argument("--files", "-f", nargs="*")
    parser.add_argument("--names", "-n", nargs="*")
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
        sys.exit(0)
    if args.env:
        print(
            "WEB3_SOL_SRCDIR=src/sol\n"
            "WEB3_SOLC_VER=0.8.9\n"
            "WEB3_BUILD_DIR=build/web3deploy\n"
            "WEB3_HTTP_PROVIDER=http://localhost:8545\n"
            "WEB3_POA=True\n"
            "WEB3_KEY_INDEX=0\n"
        )
        sys.exit(0)

    build_dir = config("WEB3_BUILD_DIR", default="build/web3deploy")
    contract_dir = f"{build_dir}/contract"
    if args.clear:
        try:
            os.rmdir(contract_dir)
        except Exception as e:
            rlog.warning(f"error removing contract directory: {e}")
        sys.exit(0)

    return args


def deploy():
    args = _parse_cmdline()

    # locate contract files in package directory
    sol_src_dir = config("WEB3_SOL_SRCDIR", default="src/sol")
    if args.files:
        contract_files = args.files
    else:
        contract_files = glob.glob(f"{sol_src_dir}/*.sol")

    rlog.info(f"{contract_files =}")

    # compile contract files
    compiler_ver = config("WEB3_SOLC_VER", default="0.8.9")
    rlog.info(f"optimize={bool(args.optimize)}, runs={args.optimize} {compiler_ver=}")
    if args.optimize:
        optimize_kwargs = {"optimize": bool(args.optimize), "optimize_runs": args.optimize}
    else:
        optimize_kwargs = {}

    # ensure build directory is created
    build_dir = config("WEB3_BUILD_DIR", default="build/web3deploy")
    contract_dir = f"{build_dir}/contract"
    if not os.path.exists(contract_dir):
        os.makedirs(contract_dir)

    # read existing address data into memory
    try:
        with open(f"{build_dir}/address.json", "r") as f:
            old_address_dct = json.load(f)
    except FileNotFoundError as e:
        rlog.warning(f"address.json not found: {e}")
        old_address_dct = {}

    if args.names:
        contract_names = args.names
    else:
        contract_names = [_get_contract_name(cfile) for cfile in contract_files]

    address_dct = {}
    for contract_file, contract_name in zip(contract_files, contract_names):
        compiled_contract = solcx.compile_files(
            [contract_file],
            solc_version=compiler_ver,
            base_path=os.getcwd(),
            allow_paths=os.getcwd(),
            **optimize_kwargs,
        )

        # write output abi to build files
        with open(f"{contract_dir}/{contract_name}.json", "w") as f:
            json.dump(compiled_contract, f)

        # deploy contract across web3
        w3 = Web3(
            Web3.HTTPProvider(config("WEB3_HTTP_PROVIDER", default="http://localhost:8545"))
        )

        if config("WEB3_POA", default=False, cast=bool):
            rlog.info("Injecting geth_poa_middleware")
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        w3.eth.default_account = w3.eth.accounts[config("WEB3_KEY_INDEX", cast=int, default=0)]

        for contract_id, contract_interface in compiled_contract.items():
            section_name = contract_id.split(":")[-1]
            if section_name == contract_name:
                contract = w3.eth.contract(
                    abi=contract_interface["abi"], bytecode=contract_interface["bin"]
                )
                tx_hash = contract.constructor().transact()
                tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                address_dct[contract_name] = tx_receipt.contractAddress
                rlog.info(f"contract {contract_name}: {tx_receipt.contractAddress}")

    # merge old_address_dct into address_dct
    address_dct = old_address_dct | address_dct

    # save contract deploy data to disk
    with open(f"{build_dir}/address.json", "w") as f:
        json.dump(address_dct, f)
