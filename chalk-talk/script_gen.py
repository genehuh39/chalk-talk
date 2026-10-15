"""Write the ~30s chalk-talk script with Claude (direct API or Vercel AI Gateway).

Config (env or .env):
    LLM_PROVIDER    gateway (default) | anthropic
    AI_GATEWAY_API_KEY   for gateway
    ANTHROPIC_API_KEY    for anthropic (or an `ant auth login` profile)
    LLM_MODEL       optional override (default: anthropic/claude-opus-5.5 | claude-opus-5-5)

Usage: python script_gen.py --play shotgun_mesh
"""
import argparse
import json
import os

import anthropic
from dotenv import load_dotenv

import playbook

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env.local"))  # .env.local wins over .env
load_dotenv(os.path.join(_HERE, ".env"))

GATEWAY_URL = "https://ai-gateway.vercel.sh"
DEFAULT_MODELS = {"gateway": "anthropic/claude-opus-5.5", "anthropic": "claude-opus-5-5"}
MIN_WORDS, MAX_WORDS = 62, 82

CUE_DOCS = {
    "show_formation": "the offense's formation is drawn on the board",
    "run_play": "the offense's play (routes / run path) is drawn in",
    "show_defense": "the defense is drawn in with its assignments",
    "highlight_key": "a red circle spotlights the one defender who wins the rep",
    "play_vs_defense": "the play runs live into the defense and gets stopped",
    "recap": "the defense's name is stamped big on the board",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "On-screen hook, 3-6 words, e.g. 'How to kill the Mesh'"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cue": {"type": "string", "enum": list(CUE_DOCS)},
                    "narration": {"type": "string"},
                },
                "required": ["cue", "narration"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "beats"],
    "additionalProperties": False,
}

SYSTEM = f"""You write scripts for short vertical football videos (TikTok/Reels/Shorts). A coach's face talks in \
the corner while an animated chalkboard illustrates the play. Your job: explain, in about 30 seconds, which \
defense beats a given offensive play and why.

Voice: an energetic, confident football coach talking to players and fans. Short, punchy spoken sentences. \
No jargon without a quick plain-English gloss. Open with a hook in the first beat. Name the defense clearly. \
Land on the ONE key reason it works, tied to the key defender. End with a confident one-liner.

The script is a list of beats. Each beat is one or two sentences of narration plus the chalkboard cue that \
plays while it's spoken:
{chr(10).join(f"- {k}: {v}" for k, v in CUE_DOCS.items())}

Rules:
- 5 to 7 beats, {MIN_WORDS}-{MAX_WORDS} words of narration in total (it's read aloud in ~30 seconds).
- First beat is show_formation. Last beat is recap.
- Include run_play, show_defense, highlight_key and play_vs_defense, in that order (you may repeat a cue).
- Stick to the facts you're given about the play and the defense; don't invent other schemes or players.
- Write narration exactly as it should be spoken: no stage directions, no emoji, no hashtags. Spell numbers \
the way they're said ("Cover one", "eight-man front")."""


def make_client():
    provider = os.getenv("LLM_PROVIDER", "gateway").lower()
    if provider == "gateway":
        key = os.getenv("AI_GATEWAY_API_KEY")
        if not key:
            raise RuntimeError("AI_GATEWAY_API_KEY is not set (put it in chalk-talk/.env.local)")
        client = anthropic.Anthropic(api_key=key, base_url=GATEWAY_URL)
    elif provider == "anthropic":
        client = anthropic.Anthropic()
    else:
        raise RuntimeError(f"unknown LLM_PROVIDER {provider!r} (use gateway or anthropic)")
    return provider, client, os.getenv("LLM_MODEL") or DEFAULT_MODELS[provider]


def play_brief(play):
    form = playbook.FORMATIONS[play["formation"]]
    key = next(d for d in play["defense"] if d["id"] == play["key_defender"])
    return json.dumps({
        "formation": f"{form['name']}: {form['personnel']}. {form['blurb']}",
        "play": f"{play['name']} ({play['type']}). {play['concept']}",
        "defense": f"{play['defense_name']}. {play['defense_detail']}",
        "why_it_works": play["why_it_works"],
        "key_defender": f"{key['id']} (callout on screen: '{play['key_label']}')",
        "result_on_screen": play["stop_text"],
    }, indent=1)


def validate(script):
    problems = []
    beats = script.get("beats", [])
    cues = [b["cue"] for b in beats]
    words = sum(len(b["narration"].split()) for b in beats)
    if not 5 <= len(beats) <= 7:
        problems.append(f"has {len(beats)} beats; needs 5-7")
    if not MIN_WORDS <= words <= MAX_WORDS:
        problems.append(f"has {words} words; needs {MIN_WORDS}-{MAX_WORDS}")
    if cues[:1] != ["show_formation"]:
        problems.append("first beat must be show_formation")
    if cues[-1:] != ["recap"]:
        problems.append("last beat must be recap")
    order = ["run_play", "show_defense", "highlight_key", "play_vs_defense"]
    firsts = [cues.index(c) if c in cues else None for c in order]
    if None in firsts:
        problems.append("must include " + ", ".join(c for c, i in zip(order, firsts) if i is None))
    elif firsts != sorted(firsts):
        problems.append("cues must first appear in the order run_play, show_defense, highlight_key, play_vs_defense")
    return problems


def generate(play_id, max_attempts=2):
    play = playbook.PLAYS[play_id]
    provider, client, model = make_client()
    messages = [{"role": "user", "content": "Write the script for this play.\n\n" + play_brief(play)}]
    problems = []
    for _ in range(max_attempts):
        kwargs = dict(
            model=model,
            max_tokens=4000,
            system=SYSTEM,
            messages=messages,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if provider == "anthropic":
            # Server-side refusal fallback (Claude API only)
            response = client.beta.messages.create(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            response = client.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            raise RuntimeError("the model declined to write this script")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("the script response was cut off (max_tokens)")
        text = next(b.text for b in response.content if b.type == "text")
        script = json.loads(text)
        problems = validate(script)
        if not problems:
            return script
        # Ask for a corrected version, keeping the conversation append-only
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": "Revise it: the script " + "; ".join(problems) + "."},
        ]
    raise RuntimeError("script failed validation: " + "; ".join(problems))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--play", required=True, choices=sorted(playbook.PLAYS))
    args = ap.parse_args()
    s = generate(args.play)
    print(json.dumps(s, indent=1))
    print("words:", sum(len(b["narration"].split()) for b in s["beats"]))
