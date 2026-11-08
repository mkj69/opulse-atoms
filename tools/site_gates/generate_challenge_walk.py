"""Generate the correct browser walk from the public roads checker, without shipping its answer."""

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "docs/assets/js/atoms2/roads.js"
GRAPH = ROOT / "docs/assets/data/atoms2/roads.json"
OUTPUT = ROOT / "build/site_gates/walk_challenge_correct.json"


def generate_walk(output=OUTPUT):
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required to generate the challenge walk")
    script = """const roads = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
const answer = roads.worst(graph, 'A', 'L', 2);
if (answer.disconnected || !roads.judge(graph, answer.closed, answer.route).correct)
  throw new Error('No valid roads witness');
process.stdout.write(JSON.stringify(answer));"""
    result = subprocess.run([node, "-e", script, str(CHECKER), str(GRAPH)],
                            capture_output=True, text=True, check=True)
    answer = json.loads(result.stdout)
    closed = ", ".join(answer["closed"])
    route = ", ".join(answer["route"])
    query = urlencode({"closed": ",".join(answer["closed"]),
                       "route": ",".join(answer["route"]), "check": "1"})
    walk = {
        "pages": {"challenge": "/play/challenge/"},
        "urls": ["challenge"],
        "steps": [
            {"wait": {"text": "Check answer", "timeout": 15}},
            {"fill": {"selector": "[data-roads-challenge] input[name='closed']", "value": closed}},
            {"fill": {"selector": "[data-roads-challenge] input[name='route']", "value": route}},
            {"open": "/play/challenge/?" + query},
            {"wait": {"text": "Correct. Cost", "timeout": 15}},
            {"assert_text": "Correct. Cost"},
            {"assert_text": "closures inspected in your browser."},
        ],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(walk, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    print(generate_walk())
