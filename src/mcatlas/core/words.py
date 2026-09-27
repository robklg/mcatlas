"""Words people read outside the site: the atlas pages, the 3D map markers, the notes README.

One `Words` per language; every field is required, so a text missing in one language is a type
error. Templates use `str.format` fields; pairs are (one, other) for counts. The site has its own
texts (site_assets/i18n.js), since the browser switches language there.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

from mcatlas.core.model import GameMode, Language, WorldFormat

type Plural = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Words:
    lang: Language
    thousands: str
    decimal: str
    months: tuple[str, ...]
    months_short: tuple[str, ...]
    modes: Mapping[GameMode, str]
    generators: Mapping[str, str]
    formats: Mapping[WorldFormat, str]
    dimensions: Mapping[str, str]
    importance: Mapping[str, str]
    text_kinds: Mapping[str, str]
    """Heading per kind of text; in lower case they also count texts ("signs 3")."""

    worlds: Plural
    days: Plural
    months_count: Plural
    sessions: Plural
    blocks: Plural
    files: Plural
    hours: str
    """Hours of play time, after the number."""

    # 3D map markers
    site_label: str
    spawn_label: str
    spawn_detail: str
    marker_set: str
    built_detail: str
    below_detail: str

    # index page
    index_title: str
    played_between: str
    index_intro: str
    as_spreadsheet: str
    per_month: str
    timeline_title: str
    timeline_link: str
    timeline_intro: str
    timeline_world: str
    timeline_total: str
    timeline_all: str
    index_header: tuple[str, ...]
    orphans_heading: str
    orphans_text: str

    # world page: summary
    kind: str
    period: str
    active_days: str
    in_months: str
    own_players: str
    left_running: str
    play_time: str
    items_used: str
    items_used_value: str
    built: str
    below: str
    by_makers: str
    by_makers_value: str
    explored: str
    version: str
    game_mode: str
    cheats_on: str
    world_type: str
    mods: str
    yes: str
    datapacks: str
    last_opened: str
    size: str
    size_value: str
    importance_label: str

    # world page: sections
    in_archive: str
    folder_name: str
    all_worlds: str
    facts_link: str
    icon_alt: str
    summary: str
    sites_heading: str
    sites_text: str
    sites_header: tuple[str, ...]
    height_range: str
    site_alt: str
    site_caption: str
    around: str
    spawn_alt: str
    spawn_caption: str
    top_blocks: str
    top_blocks_header: tuple[str, ...]
    chunks_alt: str
    chunks_caption: str
    chunks_elsewhere: Plural
    underground_alt: str
    underground_caption: str
    maps_heading: str
    maps_count: Plural
    maps_intro: str
    maps_newest: str
    mosaic_alt: str
    mosaic_caption: str
    map_alt: str
    map_caption: str
    map_locked: str
    players_heading: str
    players_header: tuple[str, ...]
    timeline: str
    timeline_text: str
    history: str
    history_text: str
    note_heading: str
    note_source: str
    texts_heading: str
    texts_found: str
    texts_link: str
    related: str
    related_text: str
    similarity: str
    problems: str

    # texts page
    texts_title: str
    texts_intro: str
    texts_history: str
    texts_history_text: str
    book_in: str
    texts_header: tuple[str, ...]

    # README of the atlas and of the notes folder
    readme_title: str
    readme_made: str
    readme: str
    notes_readme: str


def num(w: Words, n: float, decimals: int = 0) -> str:
    text = f"{n:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", w.decimal).replace("\0", w.thousands)


def count(w: Words, n: int, forms: Plural) -> str:
    return f"{num(w, n)} {forms[0] if n == 1 else forms[1]}"


def day(w: Words, d: date) -> str:
    return f"{d.day} {w.months[d.month - 1]} {d.year}"


def hours(w: Words, h: float) -> str:
    if h <= 0:
        return "–"
    if h < 1:
        return f"{round(h * 60)} min"
    return f"{num(w, h, 1 if h < 10 else 0)} {w.hours}"


NL: Final = Words(
    lang="nl",
    thousands=".",
    decimal=",",
    months=(
        "januari",
        "februari",
        "maart",
        "april",
        "mei",
        "juni",
        "juli",
        "augustus",
        "september",
        "oktober",
        "november",
        "december",
    ),
    months_short=(
        "jan",
        "feb",
        "mrt",
        "apr",
        "mei",
        "jun",
        "jul",
        "aug",
        "sep",
        "okt",
        "nov",
        "dec",
    ),
    modes={
        GameMode.SURVIVAL: "Overleven",
        GameMode.CREATIVE: "Creatief",
        GameMode.ADVENTURE: "Avontuur",
        GameMode.SPECTATOR: "Toeschouwer",
    },
    generators={
        "default": "Normaal",
        "flat": "Superflat",
        "void": "Leeg (void)",
        "amplified": "Amplified",
        "large_biomes": "Grote biomen",
        "single_biome": "Eén bioom",
        "debug": "Debug",
        "custom": "Aangepast",
        "unknown": "Onbekend",
    },
    formats={
        WorldFormat.MCREGION: "Oud formaat (Beta), niet diep geanalyseerd",
        WorldFormat.NO_TERRAIN: "Geen terrein",
        WorldFormat.NO_LEVEL_DAT: "Geen level.dat",
        WorldFormat.EMPTY: "Lege map",
    },
    dimensions={
        "minecraft:overworld": "Bovenwereld",
        "minecraft:the_nether": "Nether",
        "minecraft:the_end": "End",
    },
    importance={
        "days": "dagen",
        "weeks": "weken",
        "play_hours": "speeltijd",
        "items_used": "items",
        "chunks": "gebied",
        "built": "gebouwd",
    },
    text_kinds={"sign": "Bordjes", "book": "Boeken", "name": "Namen", "command": "Commando's"},
    worlds=("wereld", "werelden"),
    days=("dag", "dagen"),
    months_count=("maand", "maanden"),
    sessions=("sessie", "sessies"),
    blocks=("blok", "blokken"),
    files=("bestand", "bestanden"),
    hours="uur",
    site_label="Plek {n}",
    spawn_label="Spawn",
    spawn_detail="startpunt van de wereld",
    marker_set="Bouwplekken",
    built_detail="{n} blokken gebouwd",
    below_detail="{pct}% onder de grond",
    index_title="Minecraft-werelden",
    played_between="Gespeeld tussen {first} en {last}. ",
    index_intro=(
        "{worlds}, van meest naar minst gespeeld (belangrijkheid). {period}"
        "Bijgewerkt op {day}. Uitleg: "
    ),
    as_spreadsheet="; als spreadsheet: ",
    per_month="; per maand: ",
    timeline_title="Tijdlijn: speeldagen per maand",
    timeline_link="tijdlijn",
    timeline_intro=(
        "Per jaar de werelden waarin dat jaar gespeeld is, op volgorde van de eerste speeldag, "
        "met per maand het aantal dagen met bewijs dat er gespeeld is (een ondergrens, zie de "
        "README). Activiteit van de makers van gedownloade maps telt niet mee."
    ),
    timeline_world="Wereld",
    timeline_total="Jaar",
    timeline_all="Speeldagen (alle werelden)",
    index_header=(
        "#",
        "Wereld",
        "Periode",
        "Dagen",
        "Speeltijd",
        "Gebouwd",
        "Ondergronds",
        "Spelers",
        "Notitie",
    ),
    orphans_heading="Notities zonder wereld",
    orphans_text="Deze notities in {dir}/ horen bij werelden die niet meer in het archief staan:",
    kind="Soort",
    period="Periode",
    active_days="Actieve dagen",
    in_months=" in {months}",
    own_players=" (eigen spelers; alle spelers samen {hours})",
    left_running="; waarschijnlijk vaak aan laten staan",
    play_time="Speeltijd",
    items_used="Items gebruikt",
    items_used_value="{n} (inclusief elk geplaatst blok)",
    built="Gebouwd",
    below="{pct}% onder de grond",
    by_makers="Van de makers",
    by_makers_value="{n} blokken (van vóór onze spelers)",
    explored="Verkend",
    version="Versie",
    game_mode="Spelmodus",
    cheats_on="cheats aan",
    world_type="Wereldtype",
    mods="Mods",
    yes="ja",
    datapacks="Datapacks",
    last_opened="Laatst geopend",
    size="Grootte",
    size_value="{mb} MB in {files}",
    importance_label="Belangrijkheid",
    in_archive="Map in het archief: ",
    folder_name=" (mapnaam {folder})",
    all_worlds="← alle werelden",
    facts_link="feiten (facts.toml)",
    icon_alt="Plaatje van de wereld",
    summary="Samenvatting",
    sites_heading="Bouwplekken",
    sites_text=(
        "Plekken waar gebouwd is, groot naar klein. Midden = x en z in blokken; de "
        "teleport-opdracht werkt in een kopie van de wereld met cheats aan."
    ),
    sites_header=(
        "#",
        "Dimensie",
        "Midden",
        "Gebied",
        "Hoogte",
        "Blokken",
        "Ondergronds",
        "In de buurt",
        "Teleport",
    ),
    height_range="{low} tot {high}",
    site_alt="Plek {n} van bovenaf",
    site_caption="Plek {n} ({dimension}, rond {x} {z}) van bovenaf, noorden boven.",
    around=" rond {x} {z}",
    spawn_alt="Spawn van bovenaf",
    spawn_caption="Het gebied{around} van bovenaf.",
    top_blocks="Meest gebouwde blokken",
    top_blocks_header=("Blok", "Aantal"),
    chunks_alt="Wat er gebouwd is, van bovenaf",
    chunks_caption=(
        "Van bovenaf, per chunk van 16 × 16 blokken, noorden boven; 1 pixel is {blocks}. "
        "Lichtgrijs is land, oranje is gebouwd: van licht (1 tot 9 blokken in een chunk) via "
        "10, 100 en 1.000 tot donker (10.000 of meer). Omkaderd de bouwplekken met hun nummer."
    ),
    chunks_elsewhere=(
        " {n} chunk met bouwsels ligt verder weg en staat niet op de kaart.",
        " {n} chunks met bouwsels liggen verder weg en staan niet op de kaart.",
    ),
    underground_alt="Boven of onder de grond, van bovenaf",
    underground_caption=(
        "Dezelfde kaart voor chunks met minstens 20 gebouwde blokken: groen is vooral "
        "bovengronds gebouwd, bruin vooral ondergronds, grijs half om half."
    ),
    maps_heading="Kaarten in het spel",
    maps_count=("kaart", "kaarten"),
    maps_intro="{maps}, waarvan {filled} ingevuld.",
    maps_newest=" Hieronder de nieuwste {n}, zonder dubbele.",
    mosaic_alt="Kaarten samen ({dimension})",
    mosaic_caption=(
        "{maps} op hun plek ({dimension}, {x0} {z0} tot {x1} {z1}), noorden boven; "
        "1 pixel is {blocks}."
    ),
    map_alt="Kaart {id}",
    map_caption="Kaart #{id}: rond {x} {z}{dimension}, 1 pixel is {blocks}{locked}.",
    map_locked=", vergrendeld",
    players_heading="Spelers",
    players_header=(
        "Speler",
        "Speeltijd",
        "Sessies",
        "Items",
        "Advancements",
        "Modus",
        "Laatste positie",
    ),
    timeline="Tijdlijn",
    timeline_text=(
        "Dagen met bewijs dat er gespeeld is (opgeslagen chunks, advancements, bestanden). "
        "Het echte aantal ligt hoger: van elk stukje wereld onthoudt Minecraft alleen de "
        "laatste keer opslaan."
    ),
    history="Voorgeschiedenis",
    history_text=(
        "Activiteit van vóór onze spelers, bijvoorbeeld van de makers van een gedownloade map:"
    ),
    note_heading="Onze notitie",
    note_source="(Uit {dir}/, waar de notities zelf staan en bewerkt kunnen worden.)",
    texts_heading="Teksten",
    texts_found="Gevonden: {counts}. Alles staat in ",
    texts_link="teksten",
    related="Verwante werelden",
    related_text=(
        "Werelden met deels dezelfde geschiedenis (kopieën van elkaar of van dezelfde oorsprong):"
    ),
    similarity=" ({pct}% overeenkomst)",
    problems="Meldingen bij het analyseren",
    texts_title="Teksten in {name}",
    texts_intro=(
        "Teksten die spelers in de wereld hebben achtergelaten: op bordjes, in boeken, als "
        "naam van dieren en spullen, en in command blocks."
    ),
    texts_history="Van vóór onze spelers",
    texts_history_text=(
        "Deze teksten staan in stukken wereld die al zo waren toen onze spelers begonnen "
        "(bijvoorbeeld van de makers van een map)."
    ),
    book_in="In {holder} ",
    texts_header=("Tekst", "Op of in", "Plaats"),
    readme_title="Minecraft-werelden: atlas",
    readme_made="Gemaakt op {day} door {tool}, schema-versie {schema}, {worlds}.",
    readme="""\
Dit is een overzicht van een archief met Minecraft-werelden (bij elke wereld staat in welke
map van het archief hij zit). Het is gemaakt door *mcatlas*, een programma dat de werelden alleen
leest (nooit wijzigt) en uitzoekt wanneer, hoe lang, door wie en wat er in elke wereld gebouwd is.

Alles hier bestaat uit gewone bestanden die je zonder mcatlas kunt openen, ook over twintig jaar:

- **index.html** (in een webbrowser) of **index.md** (als tekst): alle werelden in een tabel,
  van meest naar minst gespeeld.
- **worlds.csv**: dezelfde tabel voor een spreadsheet (UTF-8, komma-gescheiden).
- **timeline.html** / **timeline.md**: per jaar een rooster van werelden × maanden met het
  aantal speeldagen.
- `worlds/<wereld>/`: per wereld een map met
  - `index.html` / `README.md`: alles wat over de wereld bekend is,
  - `facts.toml`: dezelfde feiten machineleesbaar (uitleg per veld in
    `schema/world.schema.json`),
  - `texts.html` / `texts.md`: bordjes, boeken, namen en commando's uit de wereld,
  - `chunks.png`: wat er gebouwd is, per chunk van bovenaf, met de bouwplekken genummerd
    (en `underground.png`: boven of onder de grond, bij werelden die veel ondergronds hebben),
  - `site-1.png`, `site-2.png`, ...: de bouwplekken van bovenaf (noorden boven, 1 pixel is
    1 of meer blokken), `icon.png`: het plaatje van de wereld uit het Minecraft-menu,
  - `maps/`: de kaarten die in het spel zijn gemaakt (`map_<nummer>.png`, zoals in het spel)
    en per dimensie een mozaïek met alle kaarten op hun plek (`mosaic-<dimensie>.png`).
- **annotations/**: onze eigen notities per wereld (Markdown). mcatlas overschrijft die nooit;
  de pagina's hier citeren ze alleen.

## Hoe je de getallen leest

- **Actieve dagen**: dagen waarop aantoonbaar gespeeld is. Minecraft onthoudt van elk stukje
  wereld alleen de laatste keer opslaan, dus dit is een ondergrens. Het getal erachter (bijv.
  `8–15`) is een bovengrens: het aantal keer dat het spel is afgesloten.
- **Speeltijd**: uit de statistieken van de spelers zelf; "eigen spelers" zijn de spelers met
  een bekende naam, anderen (vrienden, makers van een map) staan apart.
- **Gebouwd**: blokken die Minecraft zelf nooit neerzet (dus geen steen, aarde, bomen), ongeveer
  het aantal kubieke meters dat gebouwd is. Bouwen met natuurlijke blokken telt niet mee.
- **Ondergronds**: het deel van het gebouwde onder het natuurlijke maaiveld.
- **Bouwplekken**: groepjes chunks (16×16 blokken) waarin gebouwd is, met coördinaten.
- **Belangrijkheid**: één getal dat dagen, weken, speeltijd, items, gebied en bouwen optelt
  (elk logaritmisch), alleen om te sorteren.

## Bijwerken

Deze map wordt niet vanzelf bijgewerkt. Na een nieuwe notitie of nieuwe werelden in het archief
draai je mcatlas opnieuw (in de map van het mcatlas-project):

```sh
uv run mcatlas analyze --tier 2   # alleen bij nieuwe of veranderde werelden
uv run mcatlas render             # alleen bij nieuwe werelden: kaartjes van bovenaf
uv run mcatlas export-atlas       # deze map bijwerken
```

Alleen gewijzigde bestanden worden opnieuw geschreven. De map `annotations/` blijft altijd
onaangeroerd. De taal van deze pagina's is `language` in de configuratie van mcatlas.

## Een wereld weer spelen

Kopieer de wereldmap uit het archief naar de `saves`-map van Minecraft (Java Edition) en
open de kopie. Speel nooit in het archief zelf: Minecraft verandert een wereld zodra je hem
opent.
""",
    notes_readme="""\
# Notities bij de Minecraft-werelden

Elk `.md`-bestand hier hoort bij één wereld uit het archief. Bovenaan staan tussen `+++`-regels
een paar velden (TOML-formaat); daaronder vrije tekst.

- `world`: vaste code van de wereld (laat staan: zo weet mcatlas bij welke wereld het hoort)
- `folder`: mapnaam van de wereld in het archief
- `title`, `tags`, `rating` (1-5), `updated`: optioneel

De bestanden zijn met elke teksteditor te lezen en te bewerken, ook zonder mcatlas.
""",
)

EN: Final = Words(
    lang="en",
    thousands=",",
    decimal=".",
    months=(
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    months_short=(
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ),
    modes={
        GameMode.SURVIVAL: "Survival",
        GameMode.CREATIVE: "Creative",
        GameMode.ADVENTURE: "Adventure",
        GameMode.SPECTATOR: "Spectator",
    },
    generators={
        "default": "Default",
        "flat": "Superflat",
        "void": "Void",
        "amplified": "Amplified",
        "large_biomes": "Large biomes",
        "single_biome": "Single biome",
        "debug": "Debug",
        "custom": "Custom",
        "unknown": "Unknown",
    },
    formats={
        WorldFormat.MCREGION: "Old format (Beta), not analyzed in depth",
        WorldFormat.NO_TERRAIN: "No terrain",
        WorldFormat.NO_LEVEL_DAT: "No level.dat",
        WorldFormat.EMPTY: "Empty folder",
    },
    dimensions={
        "minecraft:overworld": "Overworld",
        "minecraft:the_nether": "Nether",
        "minecraft:the_end": "End",
    },
    importance={
        "days": "days",
        "weeks": "weeks",
        "play_hours": "play time",
        "items_used": "items",
        "chunks": "area",
        "built": "built",
    },
    text_kinds={"sign": "Signs", "book": "Books", "name": "Names", "command": "Commands"},
    worlds=("world", "worlds"),
    days=("day", "days"),
    months_count=("month", "months"),
    sessions=("session", "sessions"),
    blocks=("block", "blocks"),
    files=("file", "files"),
    hours="hours",
    site_label="Site {n}",
    spawn_label="Spawn",
    spawn_detail="where the world starts",
    marker_set="Build sites",
    built_detail="{n} blocks built",
    below_detail="{pct}% underground",
    index_title="Minecraft worlds",
    played_between="Played between {first} and {last}. ",
    index_intro=(
        "{worlds}, from most to least played (importance). {period}Updated on {day}. Explanation: "
    ),
    as_spreadsheet="; as a spreadsheet: ",
    per_month="; per month: ",
    timeline_title="Timeline: play days per month",
    timeline_link="timeline",
    timeline_intro=(
        "Per year the worlds played that year, in order of their first play day, with per "
        "month the number of days with evidence of play (a lower bound, see the README). "
        "Activity by the makers of downloaded maps is not counted."
    ),
    timeline_world="World",
    timeline_total="Year",
    timeline_all="Play days (all worlds)",
    index_header=(
        "#",
        "World",
        "Period",
        "Days",
        "Play time",
        "Built",
        "Underground",
        "Players",
        "Note",
    ),
    orphans_heading="Notes without a world",
    orphans_text="These notes in {dir}/ belong to worlds that are no longer in the archive:",
    kind="Kind",
    period="Period",
    active_days="Active days",
    in_months=" in {months}",
    own_players=" (our players; all players together {hours})",
    left_running="; probably often left running",
    play_time="Play time",
    items_used="Items used",
    items_used_value="{n} (including every block placed)",
    built="Built",
    below="{pct}% underground",
    by_makers="By the makers",
    by_makers_value="{n} blocks (from before our players)",
    explored="Explored",
    version="Version",
    game_mode="Game mode",
    cheats_on="cheats on",
    world_type="World type",
    mods="Mods",
    yes="yes",
    datapacks="Datapacks",
    last_opened="Last opened",
    size="Size",
    size_value="{mb} MB in {files}",
    importance_label="Importance",
    in_archive="Folder in the archive: ",
    folder_name=" (folder name {folder})",
    all_worlds="← all worlds",
    facts_link="facts (facts.toml)",
    icon_alt="Picture of the world",
    summary="Summary",
    sites_heading="Build sites",
    sites_text=(
        "Places where something was built, largest first. Centre = x and z in blocks; the "
        "teleport command works in a copy of the world with cheats on."
    ),
    sites_header=(
        "#",
        "Dimension",
        "Centre",
        "Area",
        "Height",
        "Blocks",
        "Underground",
        "Nearby",
        "Teleport",
    ),
    height_range="{low} to {high}",
    site_alt="Site {n} from above",
    site_caption="Site {n} ({dimension}, around {x} {z}) from above, north up.",
    around=" around {x} {z}",
    spawn_alt="Spawn from above",
    spawn_caption="The area{around} from above.",
    top_blocks="Most built blocks",
    top_blocks_header=("Block", "Count"),
    chunks_alt="What was built, from above",
    chunks_caption=(
        "From above, per chunk of 16 × 16 blocks, north up; 1 pixel is {blocks}. Light grey "
        "is land, orange is built: from light (1 to 9 blocks in a chunk) via 10, 100 and "
        "1,000 to dark (10,000 or more). Outlined: the build sites with their number."
    ),
    chunks_elsewhere=(
        " {n} chunk with building lies further away and is not on the map.",
        " {n} chunks with building lie further away and are not on the map.",
    ),
    underground_alt="Above or below ground, from above",
    underground_caption=(
        "The same map for chunks with at least 20 built blocks: green is built mostly above "
        "ground, brown mostly below it, grey half and half."
    ),
    maps_heading="In-game maps",
    maps_count=("map", "maps"),
    maps_intro="{maps}, {filled} of them filled in.",
    maps_newest=" Below are the newest {n}, without duplicates.",
    mosaic_alt="Maps together ({dimension})",
    mosaic_caption=(
        "{maps} in their places ({dimension}, {x0} {z0} to {x1} {z1}), north up; "
        "1 pixel is {blocks}."
    ),
    map_alt="Map {id}",
    map_caption="Map #{id}: around {x} {z}{dimension}, 1 pixel is {blocks}{locked}.",
    map_locked=", locked",
    players_heading="Players",
    players_header=(
        "Player",
        "Play time",
        "Sessions",
        "Items",
        "Advancements",
        "Mode",
        "Last position",
    ),
    timeline="Timeline",
    timeline_text=(
        "Days with evidence of play (saved chunks, advancements, files). The real number is "
        "higher: of every piece of the world Minecraft only remembers the last save."
    ),
    history="Earlier history",
    history_text=(
        "Activity from before our players, for example by the makers of a downloaded map:"
    ),
    note_heading="Our note",
    note_source="(From {dir}/, where the notes themselves are kept and can be edited.)",
    texts_heading="Texts",
    texts_found="Found: {counts}. Everything is in ",
    texts_link="texts",
    related="Related worlds",
    related_text=(
        "Worlds that share part of their history (copies of each other or of a common origin):"
    ),
    similarity=" ({pct}% alike)",
    problems="Problems while analyzing",
    texts_title="Texts in {name}",
    texts_intro=(
        "Texts players left in the world: on signs, in books, as names of animals and things, "
        "and in command blocks."
    ),
    texts_history="From before our players",
    texts_history_text=(
        "These texts are in parts of the world that were already like this when our players "
        "started (for example by the makers of a map)."
    ),
    book_in="In {holder} ",
    texts_header=("Text", "On or in", "Place"),
    readme_title="Minecraft worlds: atlas",
    readme_made="Made on {day} by {tool}, schema version {schema}, {worlds}.",
    readme="""\
This is an overview of an archive of Minecraft worlds (each world says in which folder of the
archive it is). It was made by *mcatlas*, a program that only reads the worlds (never changes
them) and works out when, how long, by whom and what was built in each world.

Everything here is plain files you can open without mcatlas, also twenty years from now:

- **index.html** (in a web browser) or **index.md** (as text): all worlds in a table, from
  most to least played.
- **worlds.csv**: the same table for a spreadsheet (UTF-8, comma-separated).
- **timeline.html** / **timeline.md**: per year a grid of worlds × months with the number
  of play days.
- `worlds/<world>/`: a folder per world with
  - `index.html` / `README.md`: everything known about the world,
  - `facts.toml`: the same facts, machine-readable (each field is explained in
    `schema/world.schema.json`),
  - `texts.html` / `texts.md`: signs, books, names and commands from the world,
  - `chunks.png`: what was built, per chunk from above, with the build sites numbered
    (and `underground.png`: above or below ground, for worlds with much underground),
  - `site-1.png`, `site-2.png`, ...: the build sites from above (north up, 1 pixel is 1 or
    more blocks), `icon.png`: the world's picture from the Minecraft menu,
  - `maps/`: the maps made in the game (`map_<number>.png`, as in the game) and per
    dimension a mosaic with all maps in their places (`mosaic-<dimension>.png`).
- **annotations/**: our own notes per world (Markdown). mcatlas never overwrites them; the
  pages here only quote them.

## How to read the numbers

- **Active days**: days on which play can be shown. Of every piece of the world Minecraft only
  remembers the last save, so this is a lower bound. The number after it (e.g. `8–15`) is an
  upper bound: how often the game was closed.
- **Play time**: from the players' own statistics; "our players" are the players with a known
  name, others (friends, makers of a map) are counted apart.
- **Built**: blocks Minecraft never places itself (so no stone, dirt, trees), roughly the
  number of cubic metres built. Building with natural blocks does not count.
- **Underground**: the part of what was built below the natural ground level.
- **Build sites**: groups of chunks (16×16 blocks) with building in them, with coordinates.
- **Importance**: one number that adds up days, weeks, play time, items, area and building
  (each on a log scale), only for sorting.

## Updating

This folder is not updated by itself. After a new note or new worlds in the archive, run
mcatlas again (in the folder of the mcatlas project):

```sh
uv run mcatlas analyze --tier 2   # only for new or changed worlds
uv run mcatlas render             # only for new worlds: maps from above
uv run mcatlas export-atlas       # update this folder
```

Only changed files are written again. The `annotations/` folder is never touched. The language
of these pages is `language` in the mcatlas configuration.

## Playing a world again

Copy the world's folder from the archive into Minecraft's `saves` folder (Java Edition) and
open the copy. Never play in the archive itself: Minecraft changes a world as soon as you
open it.
""",
    notes_readme="""\
# Notes on the Minecraft worlds

Each `.md` file here belongs to one world of the archive. At the top, between `+++` lines, are
a few fields (TOML format); below them free text.

- `world`: the world's fixed code (leave it: that is how mcatlas knows which world it is about)
- `folder`: the world's folder name in the archive
- `title`, `tags`, `rating` (1-5), `updated`: optional

The files can be read and edited with any text editor, also without mcatlas.
""",
)

WORDS: Final[Mapping[Language, Words]] = {"nl": NL, "en": EN}
