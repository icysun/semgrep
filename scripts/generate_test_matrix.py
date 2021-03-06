#!/usr/bin/env python3
import argparse
import collections
import glob
import io
import json
import os
import subprocess
import sys
import tempfile
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from ruamel.yaml import YAML

yaml = YAML(typ="rt")


FEATURES = ["dots", "equivalence", "metavar", "misc"]

VERBOSE_REGEXP_SYNTAX = 'OCaml Syntax: "=~/<regexp>/"'

VERBOSE_FEATURE_NAME = {
    "dots": "Wildcard Matches (...)",
    "equivalence": "Helpful Features",
    "metavar": "Named Placeholders ($X)",
    "misc": "Others",
    "metavar_equality": "Reoccurring Expressions",
    "concrete": "Exact Matches",
    "regexp": "Regular Expressions",
    "deep": "Deep (Recursive) Matching",
}

VERBOSE_SUBCATEGORY_NAME = {
    "stmt": "Statement",
    "stmts": "Statements",
    "call": "Function Call",
    "eq": "Equality Constraints",
    "nested_stmts": "Nested Statements",
    "cond": "Conditionals",
    "arg": "Argument",
    "args": "Arguments",
    "import": "Imports",
    "string": "Strings",
    "expr": "Expressions",
    "var": "Variables",
    "naming_import": "Import Renaming/Aliasing",
    "constant_propagation": "Constant Propagation",
    "fieldname": "Field Names",
    "syntax": "Single Statements",
    "exprstmt": "Expression and Statement",
}

LANGUAGE_EXCEPTIONS = {
    "java": ["naming_import"],
    "c": ["naming_import"],
    "ruby": ["naming_import", "typed"],
    "python": ["typed"],
    "js": ["typed"],
}

EXCLUDE = ["TODO", "POLYGLOT", "e2e", "OTHER"]

CHEATSHEET_ENTRIES = {
    "concrete": ["syntax"],
    "dots": [
        "args",
        "string",
        "stmts",
        "nested_stmts",
    ],  # "function-body", "class-body"}, TODO
    "metavar": [
        "call",
        "arg",
        "stmt",
        "cond",
        # "function-def", TODO
        # "class-def", TODO
        "import",
        "typed",
    ],
    "regexp": ["string"],
    "metavar_equality": ["expr", "stmt", "var"],
    "equivalence": [
        "naming_import",
        # "field-order", TODO
        # "arg-order", TODO
        "constant_propagation",
    ],
}


def find_path(
    root_dir: str, lang: str, category: str, subcategory: str, extension: str
):
    base_path = os.path.join(root_dir, lang, f"{category}_{subcategory}")
    joined = base_path + "." + extension
    if os.path.exists(joined):
        return joined
    else:
        generic_base_path = os.path.join(
            root_dir, "POLYGLOT", f"{category}_{subcategory}"
        )
        joined = generic_base_path + "." + extension
        return joined


def _single_pattern_to_dict(pattern: str, language: str) -> Dict[str, Any]:
    pattern = pattern.strip()
    if len(pattern.split("\n")) > 1:
        pattern = (
            pattern + "\n"
        )  # make sure multi-line patterns end in new-line otherwise semgrep dies # TODO is this still true?

    sgrep_config_default: Dict[str, Any] = {
        "rules": [
            {
                "id": "default-example",
                "patterns": [{"pattern": pattern}],
                "message": "msg",
                "languages": [language],
                "severity": "WARNING",
            }
        ]
    }
    sgrep_config_default["rules"][0]["patterns"][0]["pattern"] = pattern
    return sgrep_config_default


def _config_to_string(config: Any) -> str:
    stream = io.StringIO()
    yaml.dump(config, stream)
    return stream.getvalue()


def run_semgrep_on_example(lang: str, config_arg_str: str, code_path: str) -> str:
    with tempfile.NamedTemporaryFile("w") as config:
        pattern_text = open(config_arg_str).read()
        config.write(_config_to_string(_single_pattern_to_dict(pattern_text, lang)))
        config.flush()
        cmd = ["semgrep", "--json", f"--config={config.name}", code_path]
        print(">>> " + " ".join(cmd))
        output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if output.returncode == 0:
            print(output.stderr.decode("utf-8"))
            return output.stdout.decode("utf-8")
        else:
            print("ERROR: " + str(output.returncode))
            print(cmd)
            sys.exit(1)


def generate_cheatsheet(root_dir: str):
    # output : {'dots': {'arguments': ['foo(...)', 'foo(1)'], } }
    output = collections.defaultdict(
        lambda: collections.defaultdict(lambda: collections.defaultdict(list))
    )
    langs = get_language_directories(root_dir)
    for lang in langs:
        for category, subcategories in CHEATSHEET_ENTRIES.items():
            for subcategory in subcategories:

                sgrep_path = find_path(root_dir, lang, category, subcategory, "sgrep")
                code_path = find_path(
                    root_dir, lang, category, subcategory, lang_dir_to_ext(lang)
                )

                highlights = []
                if os.path.exists(sgrep_path) and os.path.exists(code_path):
                    ranges = run_semgrep_on_example(lang, sgrep_path, code_path)
                    if ranges:
                        j = json.loads(ranges)
                        for entry in j["results"]:
                            highlights.append(
                                {"start": entry["start"], "end": entry["end"]}
                            )

                entry = {
                    "pattern": read_if_exists(sgrep_path),
                    "pattern_path": os.path.relpath(sgrep_path, root_dir),
                    "code": read_if_exists(code_path),
                    "code_path": os.path.relpath(code_path, root_dir),
                    "highlights": highlights,
                }

                feature_name = VERBOSE_FEATURE_NAME.get(category, category)
                subcategory_name = VERBOSE_SUBCATEGORY_NAME.get(
                    subcategory, subcategory
                )
                if category == "regexp" and subcategory == "string":
                    subcategory_name = VERBOSE_REGEXP_SYNTAX
                language_exception = feature_name in LANGUAGE_EXCEPTIONS.get(
                    lang, []
                ) or subcategory in LANGUAGE_EXCEPTIONS.get(lang, [])
                if not language_exception:
                    output[lang][feature_name][subcategory_name].append(entry)

    return output


CSS = """
.pattern {
    background-color: #0974d7;
    color: white;
    padding: 10px;
}

.match {
    background-color: white;
    padding: 10px;
    border: 1px solid #0974d7;
    color: black;
}

.pair {
    display: flex;
    width: 100%;
    font-family: Consolas, Bitstream Vera Sans Mono, Courier New, Courier, monospace;
    font-size: 1em;
}

.example {
    padding: 10px;
    margin: 10px;
    border: 1px solid #ccc;
}

.examples {
    display: flex;
}

a {
    text-decoration: none;
    color: inherit;
}

pre {
    margin: 0;
}

.example-category {
    width: fit-content;
    border-top: 1px solid #ddd;
}

.notimplemented {
    background-color: yellow;
}

h3 {
    margin: 0;
    margin-bottom: 10px;
}
"""


def snippet_and_pattern_to_html(
    sgrep_pattern: str, sgrep_path: str, code_snippets: List[Tuple[str, str]]
):
    s = ""
    if sgrep_pattern:
        s += f'<div class="pattern"><a href="{sgrep_path}"><pre>{sgrep_pattern}</pre></a></div>'
        if len([x for x in code_snippets if x[0]]):
            snippets_html = "".join(
                [
                    f'<div class="match"><a href="{path}"><pre>{snippet}</pre></a></div>'
                    for snippet, path in code_snippets
                ]
            )
            s += f"<div>{snippets_html}</div>"
        else:
            return f'<div class="notimplemented">This is missing an example!<br/>Or it doesn\'t work yet for this language!<br/>Edit {sgrep_path}</div>'
    else:
        return ""
        s += f"<div>not implemented, no sgrep pattern at {sgrep_path}</div>"
    return s


def wrap_in_div(L: List[str], className="") -> List[str]:
    return "".join([f"<div class={className}>{i}</div>" for i in L])


def cheatsheet_to_html(cheatsheet: Dict[str, Any]):

    s = ""
    s += f"<head><style>{CSS}</style></head><body>"
    for lang, categories in cheatsheet.items():
        s += f"<h2>{lang}</h2>"
        for category, subcategories in categories.items():
            examples = []
            for subcategory, entries in subcategories.items():
                by_pattern = collections.defaultdict(list)
                for (sgrep_pattern, sgrep_path, code_snippet, code_path, _) in entries:
                    by_pattern[(sgrep_pattern, sgrep_path)].append(
                        (code_snippet, code_path)
                    )

                compiled_examples = [
                    snippet_and_pattern_to_html(pattern, pattern_path, snippets)
                    for (pattern, pattern_path), snippets in by_pattern.items()
                ]
                html = wrap_in_div(compiled_examples, className="pair")
                examples.append(
                    f'<div class="example"><h3>{subcategory}</h3>{html}</div>'
                )
            s += f'<div class="example-category"><h2>{category}</h2><div class="examples">{"".join(examples)}</div></div>'
    s += "</body>"
    return s


def read_if_exists(path: Optional[str]):
    if path and os.path.exists(path):
        text = str(open(path).read())
        return text


def lang_dir_to_ext(lang: str):
    LANG_DIR_TO_EXT = {"python": "py", "ruby": "rb"}
    return LANG_DIR_TO_EXT.get(lang, lang)


def get_emoji(count: int):
    if count == 0:
        return "\U0001F6A7"
    elif count < 5:
        return "\U0001F536"
    else:
        return "\U00002705"


def print_to_html(stats):
    def append_td(l, name):
        l.append("<td>")
        l.append(name)
        l.append("</td>")

    tags = ['<table style="text-align:center">', "<tr>"]
    languages = stats.keys()
    append_td(tags, "")
    for lang in languages:
        append_td(tags, f"<b>{lang}</b>")
    tags.append("</tr>")

    for f in FEATURES:
        tags.append("<tr>")
        append_td(tags, f"{VERBOSE_FEATURE_NAME.get(f)}")
        for lang in languages:
            append_td(tags, f"{get_emoji(stats[lang].get(f, 0))}")
        tags.append("</tr>")
    tags.append("</table>")
    return "\n".join(tags)


def compute_stats(dir_name: str, lang_dir: str):
    path = os.path.join(dir_name, lang_dir)
    count_per_feature = {}
    for f in FEATURES:
        count_per_feature[f] = len(
            glob.glob1(path, f"{f}*.{lang_dir_to_ext(lang_dir)}")
        )
    return count_per_feature


def get_language_directories(dir_name: str) -> List[str]:
    files = os.listdir(dir_name)
    return [
        f
        for f in files
        if os.path.isdir(os.path.join(dir_name, f)) and not f in EXCLUDE
    ]


def parse_args():
    p = argparse.ArgumentParser(
        description="""
        Generate cheatsheet for local viewing and semgrep-app usage.
        """,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    p.add_argument(
        "-d",
        "--directory",
        action="store",
        required=True,
        help="analyze this directory of tests",
    )
    p.add_argument(
        "-o",
        "--output-file",
        action="store",
        type=argparse.FileType("w"),
        help="output to this file",
    )

    output_group = p.add_mutually_exclusive_group(required=True)
    output_group.add_argument("-j", "--json", action="store_true", help="output JSON")
    output_group.add_argument("-t", "--html", action="store_true", help="output HTML")

    args = p.parse_args()

    return args


def main() -> None:
    args = parse_args()

    cheatsheet = generate_cheatsheet(args.directory)

    if args.json:
        output = json.dumps(cheatsheet, indent=4, separators=(",", ": "))
    elif args.html:
        output = cheatsheet_to_html(cheatsheet)

    if args.output_file:
        args.output_file.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
