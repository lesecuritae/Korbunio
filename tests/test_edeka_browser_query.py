import json
import re
import subprocess
from pathlib import Path


def test_android_browser_script_finds_exact_market_beyond_default_page():
    path = Path(__file__).resolve().parents[1] / "android/app/src/main/java/de/lesecuritae/korbuino/providers/EdekaWebFetchScript.kt"
    source = path.read_text()
    script = source.split('return """', 1)[1].split('""".trimIndent()', 1)[0]
    maximum = re.search(r"const val MAX_MARKETS = (\d+)", source).group(1)
    bridge = re.search(r'const val BRIDGE_NAME = "([^"]+)"', source).group(1)
    script = script.replace("$MAX_MARKETS", maximum).replace("$BRIDGE_NAME", bridge).replace("$postalCode", "12345")
    fixture = """
      const markets = Array.from({length:10}, (_,i) => ({id:String(i),zipCode:'99999'}));
      markets.push({id:'target',zipCode:'12345'});
      globalThis.fetch = async (path) => {
        const url = new URL(path, 'https://www.edeka.de');
        if (url.pathname.endsWith('/markets')) {
          return {ok:true,json:async()=>({markets:markets.slice(0,Number(url.searchParams.get('size')||10))})};
        }
        return {ok:true,json:async()=>({docs:url.searchParams.get('marketId')==='target'?[{preis:'1.49'}]:[]})};
      };
    """ + "globalThis." + bridge + " = {deliver: (text) => console.log(text)};\n"
    result = subprocess.run(["node", "--input-type=module", "-e", fixture + script], check=True, capture_output=True, text=True, timeout=10)
    delivered = json.loads(result.stdout)
    assert delivered["error"] is None
    assert delivered["market"]["id"] == "target"
    assert delivered["offers"]["docs"] == [{"preis": "1.49"}]
