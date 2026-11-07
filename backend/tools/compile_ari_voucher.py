"""Compile writable backgrounds and measure the supplied center's cells using rhwp 0.8.7."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import voucher_ari as ari


def nodes(node):
    yield node
    for child in node.get("children", []):
        yield from nodes(child)


def profile(x, top, width, height, size=9, leading=12, max_lines=None):
    return dict(x=round(x, 3), top=round(top, 3), width=round(width, 3), height=round(height, 3),
                size=size, leading=leading, maxLines=max_lines or max(1, int(height // leading)))


def compile_templates(executable):
    result = {"sourceHash": sha256(ari.original_file("hwpx")).hexdigest(), "fields": {}, "versions": {}, "pdfHashes": {}}
    ari.COMPILED.mkdir(exist_ok=True)
    with TemporaryDirectory() as temp:
        for template in ("form10", "form25", "form26"):
            folder = Path(temp) / template
            folder.mkdir()
            source = folder / "blank.hwpx"
            source.write_bytes(ari.build_hwpx(template, {}))
            target = ari.COMPILED / (template + ".pdf")
            subprocess.run([executable, "export-pdf", str(source), "-o", str(target), "--compat", "2024", "--profile", "print"], check=True)
            subprocess.run([executable, "export-render-tree", str(source), "-o", str(folder), "--compat", "2024"], check=True)
            pages = sorted(folder.glob("render_tree_*.json"))
            if len(pages) != (2 if template == "form25" else 1):
                raise ValueError(f"{template}: unexpected page count {len(pages)}")
            tree = list(nodes(json.loads(pages[0].read_text("utf-8"))))
            fields = {}
            if template == "form25":
                for key, label in [("contract_period", "계약기간"), ("other_terms", "기타")]:
                    line = next(n for n in tree if n["type"] == "TextLine" and label in "".join(c.get("text", "") for c in n.get("children", [])))
                    children = [c["bbox"] for c in line["children"] if c.get("text")]
                    x = max(b["x"]+b["w"] for b in children)*0.75 + 3
                    fields[key] = profile(x, line["bbox"]["y"]*.75, 538-x-5, 12, 10, 12, 1)
            else:
                cells = {(n["row"], n["col"]): n["bbox"] for n in tree if n["type"] == "Cell"}
                for key, addr in (ari.RECORD_CELLS if template == "form10" else ari.PLAN_CELLS).items():
                    b = cells[addr]
                    fields[key] = profile(b["x"]*.75+5.2,b["y"]*.75+2.5,b["w"]*.75-10.4,b["h"]*.75-5)
            result["fields"][template] = fields
            result["pdfHashes"][template] = sha256(target.read_bytes()).hexdigest()
            identity = {"source": sha256(ari.original_file("hwpx")).hexdigest(), "background": result["pdfHashes"][template],
                        "layout": fields, "renderer": 1}
            result["versions"][template] = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    (ari.COMPILED / "layout.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rhwp", help="Path to rhwp 0.8.7")
    compile_templates(parser.parse_args().rhwp)
