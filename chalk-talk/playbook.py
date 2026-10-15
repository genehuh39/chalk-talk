"""Hand-authored X's and O's for the 8 plays.

Coordinates are in yards: x is across the field (0 = ball, negative = offense's left),
y is depth from the line of scrimmage (negative = offensive backfield, positive = downfield).
The LLM never produces geometry; it only narrates over these diagrams.
"""

# Path kinds (how chalkboard.py draws them)
#   route  - solid arrow (pass route)
#   run    - thick solid arrow (ball carrier)
#   block  - short line ending in a "T"
#   pull   - solid line ending in a "T" (pulling lineman / lead blocker)
#   fake   - dashed arrow (play-action fake / read option keep)
#   drop   - dashed line, no arrowhead (QB drop / mesh)
#   rush   - defensive arrow into the backfield
#   zone   - defensive dashed drop to a spot
#   man    - defensive arrow tracking a receiver
#   fill   - thick defensive arrow (the defender who makes the play)


def P(pid, label, x, y, path=None, kind=None):
    return {"id": pid, "label": label, "pos": [x, y], "path": path or [], "kind": kind}


def ol(blocks):
    """Five offensive linemen; `blocks` maps id -> (path, kind)."""
    spots = {"LT": -4, "LG": -2, "C": 0, "RG": 2, "RT": 4}
    out = []
    for pid, x in spots.items():
        path, kind = blocks.get(pid, ([], None))
        out.append(P(pid, "", x, -0.8, path, kind))
    return out


def zone_blocks(direction):
    """Zone-blocking arrows: every lineman steps the same direction."""
    d = 1.6 * direction
    return {pid: ([[x + d, 0.6]], "block") for pid, x in
            {"LT": -4, "LG": -2, "C": 0, "RG": 2, "RT": 4}.items()}


FORMATIONS = {
    "shotgun": {
        "name": "Shotgun Spread",
        "personnel": "11 personnel (1 RB, 1 TE, 3 WR), 2x2 spread",
        "blurb": "QB 5 yards deep, two receivers each side. The most common look in football.",
    },
    "singleback": {
        "name": "Singleback (Ace)",
        "personnel": "12 personnel (1 RB, 2 TE, 2 WR)",
        "blurb": "QB under center, one back, a tight end on each side.",
    },
    "iform": {
        "name": "I-Formation",
        "personnel": "21 personnel (FB, RB, 1 TE, 2 WR)",
        "blurb": "Fullback and tailback stacked behind the QB. Old-school power.",
    },
    "pistol": {
        "name": "Pistol",
        "personnel": "11 personnel, QB at 4 yards, RB directly behind",
        "blurb": "Shotgun depth with the back lined up behind the QB for downhill run game.",
    },
}

PLAYS = {}


def play(pid, **kw):
    PLAYS[pid] = {"id": pid, **kw}


# ----------------------------------------------------------------------------
# SHOTGUN SPREAD
# ----------------------------------------------------------------------------
SHOTGUN_SKILL = lambda paths: [
    P("X", "X", -21, -0.8, *paths.get("X", ([], None))),
    P("H", "H", -15, -1.5, *paths.get("H", ([], None))),
    P("Y", "Y", 13, -0.8, *paths.get("Y", ([], None))),
    P("Z", "Z", 21, -1.5, *paths.get("Z", ([], None))),
    P("QB", "QB", 0, -5, *paths.get("QB", ([], None))),
    P("RB", "RB", 2, -5, *paths.get("RB", ([], None))),
]

play(
    "shotgun_inside_zone",
    formation="shotgun",
    name="Inside Zone",
    type="run",
    concept="Offensive line zone-blocks left in unison; the running back aims at the A/B gap and reads "
            "the first down lineman, cutting wherever a crease opens.",
    defense_name="Tite Front",
    defense_detail="3-down 'Tite' front: a nose in the center's face (0-tech) and two 4i tackles on the inside "
                   "shoulders of the offensive tackles, with linebackers stacked behind them.",
    why_it_works="Inside zone needs double-teams and a crease in the A or B gap. The Tite front puts bodies "
                 "directly over the center and guards' gaps, so the double-teams never get movement, and the "
                 "Mike linebacker can fast-flow downhill into the one gap that's left. No crease, no cutback.",
    key_defender="MIKE",
    stop_point=[-0.8, 1.0],
    offense=ol(zone_blocks(-1)) + SHOTGUN_SKILL({
        "RB": ([[0.5, -3.5], [-0.8, -1.2], [-1.2, 4]], "run"),
        "QB": ([[0.8, -4.6]], "drop"),
        "X": ([[-21, 2]], "block"), "H": ([[-14.5, 1.5]], "block"),
        "Y": ([[13, 2]], "block"), "Z": ([[21, 1.5]], "block"),
    }),
    defense=[
        P("NT", "N", 0, 1, [[-0.6, -0.4]], "rush"),
        P("DT1", "T", -3.4, 1, [[-2.8, -0.4]], "rush"),
        P("DT2", "T", 3.4, 1, [[2.8, -0.4]], "rush"),
        P("EDGE1", "E", -6.5, 1, [[-6, -1]], "rush"),
        P("EDGE2", "E", 6.5, 1, [[6, -1]], "rush"),
        P("MIKE", "M", -1.5, 5, [[-1, 1.4]], "fill"),
        P("WILL", "W", 2, 5, [[0.4, 2]], "fill"),
        P("CB1", "C", -21, 7, [[-21, 5]], "zone"),
        P("CB2", "C", 21, 7, [[21, 5]], "zone"),
        P("FS", "F", -9, 12, [[-6, 9]], "zone"),
        P("SS", "S", 9, 12, [[6, 9]], "zone"),
    ],
)

play(
    "shotgun_mesh",
    formation="shotgun",
    name="Mesh",
    type="pass",
    concept="Two shallow crossers (H and Y) run across the field at 5-6 yards, rubbing past each other to "
            "shake man coverage, with a go and a post clearing the deep defenders.",
    defense_name="Cover 1 Robber",
    defense_detail="Man coverage on every receiver with one free safety deep, plus a 'robber' linebacker who "
                   "sits in the middle of the field at 6 yards with no man assignment.",
    why_it_works="Mesh wins by making man defenders run through traffic. The robber doesn't chase anyone: he "
                 "parks exactly where the crossers meet, so the 'open' receiver coming out of the rub runs "
                 "straight into him. The QB's easy throw becomes a pass breakup or an interception.",
    key_defender="ROB",
    stop_point=[0, 5.6],
    offense=ol({}) + SHOTGUN_SKILL({
        "H": ([[-13, 5], [12, 6]], "route"),
        "Y": ([[11, 5], [-12, 5]], "route"),
        "X": ([[-21, 19]], "route"),
        "Z": ([[21, 10], [13, 19]], "route"),
        "RB": ([[7, -3.5], [11, 0]], "route"),
        "QB": ([[0, -7]], "drop"),
    }),
    defense=[
        P("DE1", "E", -5.5, 1, [[-4.5, -4]], "rush"),
        P("DT1", "T", -1.5, 1, [[-1, -3]], "rush"),
        P("DT2", "T", 1.5, 1, [[1, -3]], "rush"),
        P("DE2", "E", 5.5, 1, [[4.5, -4]], "rush"),
        P("CB1", "C", -21, 1.2, [[-21, 17]], "man"),
        P("CB2", "C", 21, 1.2, [[14, 17]], "man"),
        P("NB", "N", -15, 2.5, [[-6, 5.6]], "man"),
        P("SS", "S", 13, 3, [[5, 4.8]], "man"),
        P("WILL", "W", 3, 5, [[10, 1]], "man"),
        P("ROB", "R", 0, 7, [[0, 5.6]], "fill"),
        P("FS", "F", 0, 14, [[0, 16]], "zone"),
    ],
)

# ----------------------------------------------------------------------------
# SINGLEBACK (ACE)
# ----------------------------------------------------------------------------
ACE_SKILL = lambda paths: [
    P("X", "X", -20, -0.8, *paths.get("X", ([], None))),
    P("TE1", "Y", -6, -0.8, *paths.get("TE1", ([], None))),
    P("TE2", "Y", 6, -0.8, *paths.get("TE2", ([], None))),
    P("Z", "Z", 20, -1.5, *paths.get("Z", ([], None))),
    P("QB", "QB", 0, -1.8, *paths.get("QB", ([], None))),
    P("RB", "RB", 0, -7, *paths.get("RB", ([], None))),
]

play(
    "singleback_outside_zone",
    formation="singleback",
    name="Outside Zone",
    type="run",
    concept="Everyone zone-blocks to the right; the back aims for the tight end's outside hip and either "
            "gets the edge or cuts back when the defense over-pursues.",
    defense_name="Hard-Edge Cover 2",
    defense_detail="Cover 2 with corners rolled up in the flats at 4 yards, playing the run first, plus the "
                   "defensive line slanting toward the play.",
    why_it_works="Outside zone lives on the edge. Cover 2 corners are the force players: they come downhill "
                 "and set a hard edge outside the tight end, so the back can't bounce. Meanwhile the slanting "
                 "line knocks the cutback lanes shut, and the back gets squeezed into the linebackers.",
    key_defender="CB2",
    stop_point=[7.2, 1.2],
    offense=ol(zone_blocks(1)) + ACE_SKILL({
        "RB": ([[4, -4.5], [7.5, -1.5], [7.5, 3]], "run"),
        "QB": ([[1.5, -3.5]], "drop"),
        "TE2": ([[8, 0.8]], "block"), "TE1": ([[-4, 0.8]], "block"),
        "X": ([[-20, 2]], "block"), "Z": ([[19, 2]], "block"),
    }),
    defense=[
        P("DE1", "E", -7.5, 1, [[-5.5, -0.5]], "rush"),
        P("DT1", "T", -2.5, 1, [[-0.5, -0.5]], "rush"),
        P("DT2", "T", 2.5, 1, [[4.5, -0.5]], "rush"),
        P("DE2", "E", 7.5, 1, [[9.5, -0.5]], "rush"),
        P("WILL", "W", -4, 5, [[0, 3]], "fill"),
        P("MIKE", "M", 0, 5, [[4.5, 2.5]], "fill"),
        P("SAM", "S", 5, 5, [[7, 2]], "fill"),
        P("CB1", "C", -16, 4, [[-12, 3]], "zone"),
        P("CB2", "C", 16, 4, [[10.5, 1.5]], "fill"),
        P("FS", "F", -12, 13, [[-9, 11]], "zone"),
        P("SSF", "F", 12, 13, [[10, 9]], "zone"),
    ],
)

play(
    "singleback_pa_boot",
    formation="singleback",
    name="Play-Action Boot",
    type="pass",
    concept="Fake outside zone right, then the QB bootlegs left away from the flow with a flat, a drag and "
            "a deep crosser all flooding the left side.",
    defense_name="Cover 3 with a Contain End",
    defense_detail="Cover 3 (three deep, four underneath) where the backside defensive end ignores the run "
                   "fake and stays home for contain.",
    why_it_works="The boot only works if the backside end chases the fake and leaves the QB alone on the "
                 "edge. Coach that end to stay home: he sits on the edge, the QB rolls right into him, and "
                 "the Cover 3 underneath defenders sink under the crosser. It's a sack or a throwaway.",
    key_defender="DE1",
    stop_point=[-8.5, -4],
    offense=ol(zone_blocks(1)) + ACE_SKILL({
        "QB": ([[1.8, -3.8], [-7, -5], [-9.5, -3.5]], "fake"),
        "RB": ([[4, -4.5], [6, -2]], "fake"),
        "TE1": ([[-9, 1], [-17, 2.5]], "route"),
        "TE2": ([[3, 3], [-12, 5]], "route"),
        "Z": ([[18, 9], [-11, 14]], "route"),
        "X": ([[-20, 21]], "route"),
    }),
    defense=[
        P("DE1", "E", -7.5, 1, [[-9, -1], [-8.5, -4]], "fill"),
        P("DT1", "T", -2.5, 1, [[-1.5, -2]], "rush"),
        P("DT2", "T", 2.5, 1, [[3.5, -1.5]], "rush"),
        P("DE2", "E", 7.5, 1, [[6, -3]], "rush"),
        P("SS", "S", -10, 7, [[-14, 4]], "zone"),
        P("WILL", "W", -4, 5, [[-7, 6]], "zone"),
        P("MIKE", "M", 0, 5, [[-3, 7]], "zone"),
        P("SAM", "S", 5, 5, [[9, 4]], "zone"),
        P("CB1", "C", -19, 8, [[-18, 18]], "zone"),
        P("CB2", "C", 19, 8, [[17, 18]], "zone"),
        P("FS", "F", 0, 13, [[-4, 17]], "zone"),
    ],
)

# ----------------------------------------------------------------------------
# I-FORMATION
# ----------------------------------------------------------------------------
I_SKILL = lambda paths: [
    P("X", "X", -20, -0.8, *paths.get("X", ([], None))),
    P("TE", "Y", 6, -0.8, *paths.get("TE", ([], None))),
    P("Z", "Z", 20, -1.5, *paths.get("Z", ([], None))),
    P("QB", "QB", 0, -1.8, *paths.get("QB", ([], None))),
    P("FB", "FB", 0, -4.5, *paths.get("FB", ([], None))),
    P("RB", "RB", 0, -7, *paths.get("RB", ([], None))),
]

POWER_OL = ol({
    "LT": ([[-5, 0.4]], "block"),
    "LG": ([[-1.5, -2.6], [3, -2.6], [4.6, 1]], "pull"),
    "C": ([[-1.6, 0.6]], "block"),
    "RG": ([[0.6, 0.8]], "block"),
    "RT": ([[2.6, 0.8]], "block"),
})

play(
    "iform_power",
    formation="iform",
    name="Power O",
    type="run",
    concept="Gap scheme: the play side down-blocks, the fullback kicks out the end man, and the backside "
            "guard pulls through the hole to lead for the tailback.",
    defense_name="8-Man Front, Spill",
    defense_detail="Drop a safety into the box for eight defenders. The end 'wrong-arms' the fullback's "
                   "kick-out block (attacks it with his inside shoulder), and the extra safety fills outside.",
    why_it_works="Power needs the fullback to kick the end out so the guard can lead up through a clean "
                 "hole. Wrong-arming the kick-out blows up both blockers in the hole and spills the back to "
                 "the outside, where the eighth defender, the safety who rotated down, is unblocked and "
                 "waiting.",
    key_defender="SS",
    stop_point=[7.8, 0.6],
    offense=POWER_OL + I_SKILL({
        "FB": ([[3, -2.5], [6.8, -0.6]], "pull"),
        "RB": ([[1, -4.5], [4.4, -1.2], [5, 4]], "run"),
        "QB": ([[1.4, -3.2]], "drop"),
        "TE": ([[4.6, 0.8]], "block"),
        "X": ([[-20, 2]], "block"), "Z": ([[19, 2]], "block"),
    }),
    defense=[
        P("DE1", "E", -6.5, 1, [[-5, -1]], "rush"),
        P("DT1", "T", -2.5, 1, [[-2, -0.5]], "rush"),
        P("DT2", "T", 2.5, 1, [[2.5, -0.5]], "rush"),
        P("DE2", "E", 8, 1, [[5.8, -0.8]], "rush"),
        P("WILL", "W", -4, 5, [[0, 2]], "fill"),
        P("MIKE", "M", 0, 5, [[3.5, 1.5]], "fill"),
        P("SAM", "S", 4.5, 5, [[5.5, 1.5]], "fill"),
        P("SS", "S", 10, 4.5, [[7.8, 0.6]], "fill"),
        P("CB1", "C", -20, 6, [[-20, 8]], "man"),
        P("CB2", "C", 20, 6, [[20, 8]], "man"),
        P("FS", "F", 0, 13, [[3, 10]], "zone"),
    ],
)

play(
    "iform_pa_post",
    formation="iform",
    name="Play-Action Post",
    type="pass",
    concept="Fake the power run to suck up the safeties, then hit the Z receiver on a deep post behind "
            "them, with a dig and a short out underneath.",
    defense_name="Quarters (Cover 4)",
    defense_detail="Four deep: each corner and safety takes a quarter of the field. Safeties read the #2 "
                   "receiver (here the tight end) to decide whether to help on the run or cap deep routes.",
    why_it_works="Play-action post is built to punish a safety who bites on the run. In Quarters the safety "
                 "keys the tight end, not the backfield. The tight end runs a short out, which tells the "
                 "safety it's a pass, so he stays deep and caps the post. The corner stays outside, the "
                 "post is bracketed, and there's nothing deep to throw to.",
    key_defender="S2",
    stop_point=[11, 19.5],
    offense=ol({}) + I_SKILL({
        "QB": ([[1.4, -3.2], [0, -8]], "fake"),
        "FB": ([[4, -1.5]], "fake"),
        "RB": ([[1.5, -4]], "fake"),
        "Z": ([[19.5, 11], [10, 21]], "route"),
        "X": ([[-20, 13], [-6, 13]], "route"),
        "TE": ([[6, 6], [12, 6.5]], "route"),
    }),
    defense=[
        P("DE1", "E", -6.5, 1, [[-4.5, -4]], "rush"),
        P("DT1", "T", -2.5, 1, [[-1.5, -3]], "rush"),
        P("DT2", "T", 2.5, 1, [[1.5, -3]], "rush"),
        P("DE2", "E", 8, 1, [[5.5, -4]], "rush"),
        P("WILL", "W", -4, 5, [[-6, 8]], "zone"),
        P("MIKE", "M", 0, 5, [[0, 8]], "zone"),
        P("SAM", "S", 4.5, 5, [[9, 6]], "zone"),
        P("CB1", "C", -20, 7, [[-19, 16]], "zone"),
        P("CB2", "C", 20, 7, [[17, 19]], "zone"),
        P("S1", "F", -9, 10, [[-7, 15]], "zone"),
        P("S2", "S", 9, 10, [[11, 19.5]], "fill"),
    ],
)

# ----------------------------------------------------------------------------
# PISTOL
# ----------------------------------------------------------------------------
PISTOL_SKILL = lambda paths: [
    P("X", "X", -21, -0.8, *paths.get("X", ([], None))),
    P("H", "H", -14, -1.5, *paths.get("H", ([], None))),
    P("TE", "Y", 6, -0.8, *paths.get("TE", ([], None))),
    P("Z", "Z", 21, -1.5, *paths.get("Z", ([], None))),
    P("QB", "QB", 0, -4, *paths.get("QB", ([], None))),
    P("RB", "RB", 0, -7, *paths.get("RB", ([], None))),
]

play(
    "pistol_zone_read",
    formation="pistol",
    name="Zone Read",
    type="run",
    concept="The line zone-blocks right and leaves the backside defensive end unblocked. The QB reads him: "
            "if the end crashes on the back, the QB pulls it and runs where the end used to be.",
    defense_name="Scrape Exchange",
    defense_detail="The unblocked end crashes hard at the running back, and the linebacker behind him "
                   "'scrapes' over the top to take the quarterback.",
    why_it_works="The zone read puts one defender in a two-on-one bind. The scrape exchange gives him help: "
                 "the end crashes to take the back, which tells the QB to keep it, but the Will linebacker "
                 "has already swapped responsibilities and is scraping outside, right into the QB's path. "
                 "The QB's read says 'keep', and he gets tackled anyway.",
    key_defender="WILL",
    stop_point=[-7.6, 0.2],
    offense=ol(zone_blocks(1)) + PISTOL_SKILL({
        "RB": ([[1.2, -4.5], [3.2, -1.2], [3.5, 4]], "run"),
        "QB": ([[-0.2, -4.3], [-5, -3.5], [-8.5, 0.5], [-9, 5]], "fake"),
        "X": ([[-21, 2]], "block"), "H": ([[-13.5, 1.5]], "block"),
        "TE": ([[8, 0.8]], "block"), "Z": ([[20, 2]], "block"),
    }),
    defense=[
        P("DE1", "E", -6.5, 1, [[-2.4, -3.6]], "rush"),
        P("DT1", "T", -2.5, 1, [[-1.2, -0.6]], "rush"),
        P("DT2", "T", 2.5, 1, [[3.8, -0.6]], "rush"),
        P("DE2", "E", 8, 1, [[8.8, -0.8]], "rush"),
        P("WILL", "W", -4, 5, [[-7.6, 0.2]], "fill"),
        P("MIKE", "M", 1, 5, [[3.5, 2]], "fill"),
        P("NB", "N", -13, 4, [[-12, 3]], "zone"),
        P("CB1", "C", -21, 7, [[-21, 5]], "zone"),
        P("CB2", "C", 21, 7, [[21, 5]], "zone"),
        P("FS", "F", -9, 12, [[-8, 8]], "zone"),
        P("SS", "S", 9, 12, [[6, 8]], "zone"),
    ],
)

play(
    "pistol_smash",
    formation="pistol",
    name="Smash",
    type="pass",
    concept="A two-man high-low: the outside receiver runs a 5-yard hitch and the slot runs a corner route "
            "over the top, putting the flat defender in conflict.",
    defense_name="Cover 3 Sky",
    defense_detail="Three deep (corners and free safety each take a deep third) with the nickel and Sam as "
                   "curl-to-flat defenders underneath.",
    why_it_works="Smash kills Cover 2 because the corner can only cover one of the two routes. In Cover 3 "
                 "the corner bails to his deep third, so he's sitting right on top of the corner route, and "
                 "the nickel is free to drive on the hitch. Both levels of the high-low are covered.",
    key_defender="CB1",
    stop_point=[-19.5, 15.5],
    offense=ol({}) + PISTOL_SKILL({
        "X": ([[-21, 5], [-20.4, 4]], "route"),
        "H": ([[-14, 10], [-19.5, 15.5]], "route"),
        "Z": ([[21, 5], [20.4, 4]], "route"),
        "TE": ([[6, 10], [12.5, 15.5]], "route"),
        "RB": ([[-3, -5], [-6, -1]], "route"),
        "QB": ([[0, -7]], "drop"),
    }),
    defense=[
        P("DE1", "E", -5.5, 1, [[-4.5, -5]], "rush"),
        P("DT1", "T", -1.5, 1, [[-1, -4]], "rush"),
        P("DT2", "T", 1.5, 1, [[1, -4]], "rush"),
        P("DE2", "E", 5.5, 1, [[4.5, -5]], "rush"),
        P("NB", "N", -14, 4, [[-19.5, 4.5]], "fill"),
        P("WILL", "W", -3, 5, [[-8, 7]], "zone"),
        P("MIKE", "M", 3, 5, [[3, 7]], "zone"),
        P("SAM", "S", 8, 4, [[17, 5]], "zone"),
        P("CB1", "C", -21, 7, [[-19.5, 15.5]], "fill"),
        P("CB2", "C", 21, 7, [[16, 16]], "zone"),
        P("FS", "F", 0, 13, [[0, 16]], "zone"),
    ],
)


# On-screen chalk callouts: (label next to the key defender, result stamped at the stop point)
CALLOUTS = {
    "shotgun_inside_zone": ("MIKE FILLS", "STUFFED!"),
    "shotgun_mesh": ("ROBBER", "PICKED!"),
    "singleback_outside_zone": ("CORNER SETS EDGE", "STRUNG OUT!"),
    "singleback_pa_boot": ("END STAYS HOME", "SACKED!"),
    "iform_power": ("8TH MAN", "STUFFED!"),
    "iform_pa_post": ("SAFETY CAPS", "BROKEN UP!"),
    "pistol_zone_read": ("WILL SCRAPES", "STOPPED!"),
    "pistol_smash": ("CORNER SINKS", "BROKEN UP!"),
}
for _pid, (_key_label, _stop_text) in CALLOUTS.items():
    PLAYS[_pid]["key_label"] = _key_label
    PLAYS[_pid]["stop_text"] = _stop_text


def plays_for(formation_id):
    return [p for p in PLAYS.values() if p["formation"] == formation_id]


def menu():
    """Formation/play menu for the web form."""
    return [
        {"id": fid, **f, "plays": [{"id": p["id"], "name": p["name"], "type": p["type"],
                                    "defense": p["defense_name"]} for p in plays_for(fid)]}
        for fid, f in FORMATIONS.items()
    ]


assert len(PLAYS) == 8
for _p in PLAYS.values():
    assert len(_p["offense"]) == 11, (_p["id"], "offense", len(_p["offense"]))
    assert len(_p["defense"]) == 11, (_p["id"], "defense", len(_p["defense"]))
    assert _p["key_defender"] in {d["id"] for d in _p["defense"]}, _p["id"]
