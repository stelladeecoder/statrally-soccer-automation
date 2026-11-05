"""Build the same read-only dashboard for static hosting; no private inputs."""
import argparse
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE="https://raw.githubusercontent.com/stelladeecoder/statrally-soccer-automation/main/docs/predictions-public-v2.json"


def build(output):
    output.mkdir(parents=True,exist_ok=True)
    for name in ("platform.html","platform.css","platform-web.mjs","platform-ui.mjs","prediction-quality.mjs"):
        text=(ROOT/"discord-app"/name).read_text()
        text=text.replace('href="/"','href="./"').replace('href="/platform','href="./platform').replace('src="/platform','src="./platform')
        text=text.replace('from "/platform-ui.mjs"','from "./platform-ui.mjs"')
        text=text.replace('from "/prediction-quality.mjs"','from "./prediction-quality.mjs"')
        text=text.replace('fetch("/api/predictions"',f'fetch("{SOURCE}"')
        if name=="platform-web.mjs":
            text=text.replace('data=await response.json();','data=await response.json();data.stale=Date.now()-Date.parse(data.generated_at)>45*60*1000;')
        (output/("index.html" if name=="platform.html" else name)).write_text(text)
    (output/".nojekyll").write_text("")


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();build(args.output)
