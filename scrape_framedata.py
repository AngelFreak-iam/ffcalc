"""
DreamCancel Wiki - Fatal Fury: City of the Wolves Frame Data Scraper
Uses nodriver (real Chrome) to bypass Cloudflare protection.

Setup:
    pip install nodriver beautifulsoup4

Usage:
    python scrape_framedata.py
    python scrape_framedata.py --character "Hokutomaru"
    python scrape_framedata.py --output csv
"""

import asyncio
import argparse
import json
import csv
import re
from pathlib import Path
from typing import Optional

import nodriver as uc
from bs4 import BeautifulSoup

BASE_URL = "https://www.dreamcancel.com/wiki"
GAME_PATH = "Fatal_Fury:_City_of_the_Wolves"
CATEGORY_URL = f"{BASE_URL}/Category:{GAME_PATH}"

KNOWN_CHARACTERS = [
    "Rock_Howard",
    "Terry_Bogard",
    "Andy_Bogard",
    "Mai_Shiranui",
    "Tizoc",
    "Joe_Higashi",
    "B._Jenet",
    "Gato",
    "Kevin_Rian",
    "Hokutomaru",
    "Preecha",
    "Vox_Reaper",
    "Billy_Kane",
    "Marco_Rodriguez",
    "Kain_R._Heinlein",
    "Kim_Dong_Hwan",
    "Cristina_Vang",
    "Ken",
    "Mr._Big",
    "Garnet",
    "Grant",
]


async def wait_for_wiki_page(tab, timeout: int = 30) -> bool:
    """
    Poll until the page is a real wiki page (not a Cloudflare challenge).
    Returns True if wiki content loaded, False if timed out.
    """
    for _ in range(timeout * 2):  # check every 0.5s
        await asyncio.sleep(0.5)
        try:
            title = await tab.evaluate("document.title")
            if "Just a moment" not in title and "Checking" not in title:
                # Give the page JS a moment to finish rendering
                await asyncio.sleep(1)
                return True
        except Exception:
            pass
    return False


async def get_character_list(tab) -> list[str]:
    """Fetch all character slugs from the game's wiki category page."""
    print("Fetching character list from category page...")
    await tab.get(CATEGORY_URL)
    if not await wait_for_wiki_page(tab):
        print("Could not load category page, using known character list.")
        return KNOWN_CHARACTERS

    html = await tab.get_content()
    soup = BeautifulSoup(html, "lxml")

    characters = []
    mw_pages = soup.find("div", id="mw-pages")
    if mw_pages:
        for link in mw_pages.find_all("a"):
            href = link.get("href", "")
            match = re.search(rf"{re.escape(GAME_PATH)}/([^/]+)/Data$", href)
            if match:
                slug = match.group(1)
                if slug not in characters:
                    characters.append(slug)

    if characters:
        print(f"Found {len(characters)} characters from category page.")
        return characters

    print("Could not parse category page, using known character list.")
    return KNOWN_CHARACTERS


async def fetch_page_html(tab, url: str) -> Optional[str]:
    """Navigate to a URL and return the page HTML once wiki content is present."""
    try:
        await tab.get(url)
        if not await wait_for_wiki_page(tab, timeout=30):
            title = await tab.evaluate("document.title")
            print(f"  Still blocked after 30s (title: '{title}')")
            return None
        return await tab.get_content()
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def parse_frame_data_tables(html: str, character: str) -> dict:
    """Parse all wikitables from a character's /Data page, grouped by section."""
    soup = BeautifulSoup(html, "lxml")
    result = {"character": character.replace("_", " "), "moves": {}}

    content = soup.find("div", id="mw-content-text")
    if not content:
        return result

    current_section = "Uncategorized"
    for element in content.descendants:
        if not hasattr(element, "name"):
            continue

        if element.name in ("h2", "h3"):
            span = element.find("span", class_="mw-headline")
            if span:
                current_section = span.get_text(strip=True)

        if element.name == "table" and (
            "wikitable" in element.get("class", [])
            or "framedata" in " ".join(element.get("class", []))
        ):
            rows = element.find_all("tr")
            if not rows:
                continue

            headers = [th.get_text(separator=" ", strip=True) for th in rows[0].find_all(["th", "td"])]
            if not headers:
                continue

            table_data = []
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                row_dict = {
                    (headers[i] if i < len(headers) else f"col_{i}"): cell.get_text(separator=" ", strip=True)
                    for i, cell in enumerate(cells)
                }
                if any(row_dict.values()):
                    table_data.append(row_dict)

            if table_data:
                result["moves"].setdefault(current_section, []).extend(table_data)

    return result


def save_json(all_data: list[dict], output_dir: Path):
    out_path = output_dir / "frame_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON: {out_path}")


def save_csv(all_data: list[dict], output_dir: Path):
    for char_data in all_data:
        char_name = char_data["character"]
        safe_name = re.sub(r"[^\w\s-]", "", char_name).replace(" ", "_")
        out_path = output_dir / f"{safe_name}.csv"

        rows = []
        for section, moves in char_data["moves"].items():
            for move in moves:
                row = {"character": char_name, "section": section}
                row.update(move)
                rows.append(row)

        if not rows:
            print(f"  No data to save for {char_name}")
            continue

        fieldnames = list(dict.fromkeys(k for row in rows for k in row.keys()))
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Saved: {out_path}")


async def scrape(character_filter: Optional[str], output_format: str):
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    browser = await uc.start()
    tab = await browser.get(BASE_URL)

    # Wait for the initial Cloudflare check to clear
    print("Waiting for Cloudflare verification...")
    if not await wait_for_wiki_page(tab, timeout=60):
        print("ERROR: Could not pass Cloudflare challenge within 60 seconds. Exiting.")
        browser.stop()
        return
    print("Wiki loaded. Starting scrape...\n")

    if character_filter:
        slug = character_filter.replace(" ", "_")
        characters = [slug]
        print(f"Scraping single character: {slug}")
    else:
        characters = await get_character_list(tab)

    all_data = []
    for slug in characters:
        url = f"{BASE_URL}/{GAME_PATH}/{slug}/Data"
        char_display = slug.replace("_", " ")
        print(f"Fetching: {char_display}")

        html = await fetch_page_html(tab, url)
        if html is None:
            print(f"  Skipping {char_display}")
            continue

        data = parse_frame_data_tables(html, slug)
        move_count = sum(len(v) for v in data["moves"].values())
        print(f"  {move_count} moves across {len(data['moves'])} sections")
        all_data.append(data)

        await asyncio.sleep(1.5)

    browser.stop()

    if not all_data:
        print("No data collected.")
        return

    if output_format == "csv":
        save_csv(all_data, output_dir)
    else:
        save_json(all_data, output_dir)

    print(f"\nDone. Scraped {len(all_data)} characters.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", "-c", default=None)
    parser.add_argument("--output", "-o", choices=["json", "csv"], default="json")
    args = parser.parse_args()

    uc.loop().run_until_complete(scrape(args.character, args.output))
