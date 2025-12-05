import pandas as pd
import ezdxf
from pathlib import Path


CSV_PATH = "diagrams.csv"   # adjust if needed
OUT_DIR = "tower_dxf"       # output folder for DXF files

X_MIN = -15000
X_MAX = 15000

TEXT_HEIGHT = 250
TITLE_HEIGHT = 500


def normalize_base(leg_type: str) -> str:
    """
    Turn e.g. '- 3 / +0,70' or '+ 6/+0,70' or ' - 4 (-3,80)' into
    a canonical base like '-3', '6', etc.
    """
    s = leg_type.strip()
    # Cut off anything after '/' or '('
    for sep in ("/", "("):
        if sep in s:
            s = s.split(sep)[0].strip()
    # Remove all spaces
    s = s.replace(" ", "")
    # Make '+1' the same as '1'
    if s.startswith("+"):
        s = s[1:]
    return s


def compute_y_maps(df_for_tower: pd.DataFrame):
    """
    For a given tower (subset of the dataframe), compute:
      - base_order: list of base leg types in the order they appear
      - y_base_map: mapping base -> y coordinate for the 'main' variant
      - y_variant_map: mapping full Leg Type string -> y coordinate
    Pattern:
        - N at y=0
        - one 'step' = 1000 units
        - any variant with '0,70' is y_base - 700
    """
    # Determine base order in this tower, preserving CSV order
    unique_leg_types = df_for_tower["Leg Type"].unique()
    base_order = []
    seen_bases = set()
    for lt in unique_leg_types:
        b = normalize_base(lt)
        if b not in seen_bases:
            seen_bases.add(b)
            base_order.append(b)

    if "N" not in base_order:
        raise ValueError("Expected a base 'N' level in this tower, but didn't find one.")

    idx_N = base_order.index("N")

    # Map base -> y_base
    y_base_map = {}
    for i, base in enumerate(base_order):
        # One 'step' = 1000 units; N at 0
        y_base_map[base] = (idx_N - i) * 1000

    # Now map each full Leg Type (including /+0,70) to its y position
    y_variant_map = {}
    for lt in unique_leg_types:
        base = normalize_base(lt)
        y_base = y_base_map[base]
        # If this is a +0,70 variant, shift down by 700
        if "0,70" in lt:
            y = y_base - 700
        else:
            y = y_base
        y_variant_map[lt] = y

    return base_order, y_base_map, y_variant_map


def draw_tower(doc, tower_name: str, df_for_tower: pd.DataFrame):
    """
    Draws:
      - one horizontal line for each unique Leg Type (variant),
        from X_MIN to X_MAX at its y position.
      - labels (variant name) at both ends of each line.
      - a title with the tower type above the topmost line.
    """
    msp = doc.modelspace()

    _, _, y_variant_map = compute_y_maps(df_for_tower)

    all_y = list(y_variant_map.values())
    if not all_y:
        return  # nothing to draw

    # Draw one line per variant
    for leg_type, y in y_variant_map.items():
        # Horizontal line
        msp.add_line((X_MIN, y), (X_MAX, y))

        label = str(leg_type).strip()

        # Label at the beginning (slightly above the line)
        t1 = msp.add_text(label, dxfattribs={"height": TEXT_HEIGHT})
        t1.dxf.insert = (X_MIN, y + TEXT_HEIGHT)  # NO set_pos!

        # Label at the end (slightly above the line)
        t2 = msp.add_text(label, dxfattribs={"height": TEXT_HEIGHT})
        t2.dxf.insert = (X_MAX, y + TEXT_HEIGHT)  # NO set_pos!

    # Title somewhere up top
    max_y = max(all_y)
    title_y = max_y + 2_000  # some margin above the highest line

    title = f"Tower Type {tower_name}"
    title_text = msp.add_text(title, dxfattribs={"height": TITLE_HEIGHT})
    # Center-ish above the lines
    title_text.dxf.insert = (0, title_y)


def main():
    df = pd.read_csv(CSV_PATH)

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tower types in the order they appear in the CSV:
    tower_types = df["Tower Type"].unique()

    for tower in tower_types:
        df_tower = df[df["Tower Type"] == tower]

        # Create a new DXF document for each tower type
        doc = ezdxf.new(setup=True)
        draw_tower(doc, tower, df_tower)

        # Sanitize filename a bit
        safe_name = (
            str(tower)
            .replace("+", "plus")
            .replace("/", "_")
            .replace(" ", "")
        )
        out_path = out_dir / f"{safe_name}.dxf"
        doc.saveas(out_path)
        print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
