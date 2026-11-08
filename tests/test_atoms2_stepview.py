"""Pure atoms-v2 step identity and invariant contracts."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "docs/assets/js/stepview.js"


def test_operator_kind_identity_and_optional_invariant():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    source = """const fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const view=context.window.OpulseStepView;
if(view.operationIdentity(null)!==null||view.operationIdentity({})!==null)throw Error('missing data');
if(view.operationIdentity({operator_kind:'atom',atom:'add'}).layer!==0)throw Error('layer zero');
if(view.operationIdentity({operator_kind:'branch',symbol:'branch'}).node!=='case')throw Error('case node');
if(view.invariantItems(null,{}).length!==0)throw Error('optional bar');
if(view.invariantItems({result:0},{result:'Result'}).length!==1)throw Error('zero result');
"""
    subprocess.run([node, "-e", source, str(SCRIPT)], check=True, capture_output=True)
