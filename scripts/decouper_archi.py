"""Découpe docs/architecture-sprint1.md en une fiche par section (docs/archi/).

Usage : python scripts/decouper_archi.py   (depuis la racine du dépôt)
"""
import re
import unicodedata
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "docs" / "architecture-sprint1.md"
CIBLE = RACINE / "docs" / "archi"


def slug(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", texte).strip("-")[:50]


def main() -> None:
    parties = re.split(r"(?m)^(## .+)$", SOURCE.read_text(encoding="utf-8"))
    CIBLE.mkdir(parents=True, exist_ok=True)
    index = [
        "# Architecture du sprint 1, découpée par section\n",
        "Source unique : `docs/architecture-sprint1.md` (ne pas modifier ces fiches à la main : "
        "les régénérer avec `scripts/decouper_archi.py`).\n",
        "Lire SEULEMENT les fiches utiles à la tâche.\n",
    ]
    for i in range(1, len(parties), 2):
        titre, corps = parties[i][3:].strip(), parties[i + 1]
        nom = f"{(i + 1) // 2:02d}-{slug(re.sub(r'^[0-9.]+ *', '', titre))}.md"
        (CIBLE / nom).write_text(
            f"<!-- Généré depuis docs/architecture-sprint1.md -->\n## {titre}\n{corps}", encoding="utf-8"
        )
        index.append(f"- [{titre}]({nom}) · {len(corps) // 4} tokens env.")
    (CIBLE / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
