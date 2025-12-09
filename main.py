import pandas as pd
import ezdxf
from pathlib import Path
import re


CSV_PATH = "diagrams.csv"   # adjust if needed
OUT_DIR = "tower_dxf"       # output folder for DXF files

X_MIN = -15000
X_MAX = 15000

TEXT_HEIGHT = 250
TITLE_HEIGHT = 500

LEFT_LABEL_EXTRA_OFFSET = 2000  # how much further left to place left labels

# Layer names
LAYER_BASE_VARIANTS = "BASE_VARIANTS"
LAYER_OFFSET_VARIANTS = "OFFSET_VARIANTS"   # for / +0,70, / +0,50, / +whatever
LAYER_CENTERLINE = "CENTERLINE"
LAYER_ANNOTATIONS = "ANNOTATIONS"           # all text (labels + title)
LAYER_ANGLED_LINES = "ANGLED_LINES"         # the two diagonal lines


def normalize_base(leg_type: str) -> str:
    """
    From a full leg type string like:
        '- 3 / +0,70', '+ 6 / +0,70', '-1,5 / +0,5', 'N / +0,70'
    get the canonical base string:
        '-3', '6', '-1,5', 'N'
    """
    s = leg_type.strip()
    # Cut off anything after '/' or '(' -> keep only the base part
    for sep in ("/", "("):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    # Remove all spaces
    s = s.replace(" ", "")
    # Make '+1' the same as '1'
    if s.startswith("+"):
        s = s[1:]
    return s


def parse_offset_value(leg_type: str):
    """
    Find the numeric part after the '/', e.g. for:
        '-1 / +0,70'   -> 0.70
        'N / +0.50'    -> 0.50
        '+6/+0,70'     -> 0.70
        '-1,5/+0,5'    -> 0.5
    Returns float or None if no offset is present.
    """
    if "/" not in leg_type:
        return None

    # Part after the first slash
    part = leg_type.split("/", 1)[1]

    # Remove anything in parentheses (e.g. ' (+3,80)')
    part = part.split("(", 1)[0]

    # Regex: first signed number with optional decimal part
    m = re.search(r"[+-]?\d+(?:[.,]\d+)?", part)
    if not m:
        return None

    num_str = m.group(0).replace(",", ".")
    try:
        return float(num_str)
    except ValueError:
        return None


def parse_distance(val):
    """
    Parse numeric fields (e.g. 'distance on the ground', 'square half-diagonal')
    to float. Handles integers or decimals with comma or dot.
    """
    if pd.isna(val):
        return None
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def compute_y_maps(df_for_tower: pd.DataFrame):
    """
    For a given tower (subset of the dataframe), compute:
      - base_order: list of base leg types in the order encountered
      - y_base_map: mapping base -> y coordinate for the base variant
      - y_variant_map: mapping full Leg Type string -> y coordinate

    Pattern:
        Base:
          - base 'N' -> y = 0
          - base numeric value k (possibly fractional, e.g. 1.5, -1,5) -> y = -1000 * k
        Offset:
          - if we have '/ +x' -> y = y_base - x * 1000
    """
    unique_leg_types = df_for_tower["Leg Type"].unique()

    base_order = []
    y_base_map = {}
    y_variant_map = {}

    for lt in unique_leg_types:
        base = normalize_base(lt)

        # Determine (and remember) the base y
        if base not in y_base_map:
            if base == "N":
                y_base = 0.0
            else:
                # Base may be integer or fractional, with comma or dot
                try:
                    base_val = float(base.replace(",", "."))
                except ValueError:
                    # Fallback if something truly weird appears: stick it at 0
                    base_val = 0.0
                y_base = -1000.0 * base_val
            y_base_map[base] = y_base
            base_order.append(base)
        else:
            y_base = y_base_map[base]

        # Offset handling: / +x -> y = y_base - x * 1000
        offset = parse_offset_value(lt)
        if offset is not None:
            y = y_base - offset * 1000.0
        else:
            y = y_base

        y_variant_map[lt] = y

    return base_order, y_base_map, y_variant_map


def ensure_layers(doc):
    """Create layers if they don't exist yet."""
    if LAYER_BASE_VARIANTS not in doc.layers:
        doc.layers.new(name=LAYER_BASE_VARIANTS, dxfattribs={"color": 7})  # white
    if LAYER_OFFSET_VARIANTS not in doc.layers:
        doc.layers.new(name=LAYER_OFFSET_VARIANTS, dxfattribs={"color": 1})  # red
    if LAYER_CENTERLINE not in doc.layers:
        doc.layers.new(name=LAYER_CENTERLINE, dxfattribs={"color": 3})  # green
    if LAYER_ANNOTATIONS not in doc.layers:
        doc.layers.new(name=LAYER_ANNOTATIONS, dxfattribs={"color": 2})  # yellow-ish
    if LAYER_ANGLED_LINES not in doc.layers:
        doc.layers.new(name=LAYER_ANGLED_LINES, dxfattribs={"color": 4})  # cyan-ish


def draw_tower(doc, tower_name: str, df_for_tower: pd.DataFrame):
    """
    Draws:
      - horizontal lines for each Leg Type
      - labels at both ends
      - dashed vertical centerline
      - positive & negative angled lines based on 'distance on the ground'
      - for each intersection of the negative/positive angled lines with a horizontal line:
          * two vertical tick marks
          * one small horizontal connector
        all on the layer of that horizontal line
      - for every horizontal line in BASE_VARIANTS:
          * an 'angled box' on the negative side, following the angled line slope
      - title on top
    """
    ensure_layers(doc)
    msp = doc.modelspace()

    _, _, y_variant_map = compute_y_maps(df_for_tower)

    all_y = list(y_variant_map.values())
    if not all_y:
        return  # nothing to draw

    y_max = max(all_y)
    y_min = min(all_y)

    # ---------- Horizontal lines + text ----------

    for leg_type, y in y_variant_map.items():
        label = str(leg_type).strip()

        # Decide if this variant is an offset variant (has an offset value)
        offset_value = parse_offset_value(leg_type)
        is_offset_variant = offset_value is not None
        layer_name = LAYER_OFFSET_VARIANTS if is_offset_variant else LAYER_BASE_VARIANTS

        # Horizontal line (on base/offset layer)
        msp.add_line(
            (X_MIN, y),
            (X_MAX, y),
            dxfattribs={"layer": layer_name},
        )

        # Left label: placed further to the left than the line, on ANNOTATIONS layer
        left_x = X_MIN - LEFT_LABEL_EXTRA_OFFSET
        t1 = msp.add_text(
            label,
            dxfattribs={
                "height": TEXT_HEIGHT,
                "layer": LAYER_ANNOTATIONS,
            },
        )
        t1.dxf.insert = (left_x, y + TEXT_HEIGHT)

        # Right label: at the right end of the line, slightly above, on ANNOTATIONS layer
        t2 = msp.add_text(
            label,
            dxfattribs={
                "height": TEXT_HEIGHT,
                "layer": LAYER_ANNOTATIONS,
            },
        )
        t2.dxf.insert = (X_MAX, y + TEXT_HEIGHT)

    # ---------- Angled lines based on "distance on the ground" ----------

    # Find leg types for lowest and highest horizontal lines
    lowest_leg_type = min(y_variant_map, key=lambda lt: y_variant_map[lt])
    highest_leg_type = max(y_variant_map, key=lambda lt: y_variant_map[lt])

    y_low = y_variant_map[lowest_leg_type]
    y_high = y_variant_map[highest_leg_type]

    col_dist = "distance on the ground"        # column name for distances
    col_sq_half = "square half-diagonal"       # column name for square half-diagonal

    # Lowest
    df_low = df_for_tower[df_for_tower["Leg Type"] == lowest_leg_type]
    x_low = None
    if not df_low.empty and col_dist in df_low.columns:
        x_low = parse_distance(df_low.iloc[0][col_dist])

    # Highest
    df_high = df_for_tower[df_for_tower["Leg Type"] == highest_leg_type]
    x_high = None
    if not df_high.empty and col_dist in df_high.columns:
        x_high = parse_distance(df_high.iloc[0][col_dist])

    # Draw angled lines, ticks, and boxes only if we have both distances and non-zero dy
    if x_low is not None and x_high is not None and y_high != y_low:

        # Compute direction of the angled line (low -> high)
        dx = x_high - x_low
        dy = y_high - y_low

        # Extend the line 1200 units upward in Y along its current slope
        extra_y = 1200.0
        t_ext = extra_y / dy          # how much further along the line we go
        x_high_ext = x_high + dx * t_ext
        y_high_ext = y_high + extra_y

        # Positive side angled line: from lowest to *extended* highest
        msp.add_line(
            (x_low, y_low),
            (x_high_ext, y_high_ext),
            dxfattribs={"layer": LAYER_ANGLED_LINES},
        )

        # Negative side: mirrored around the centerline (x -> -x)
        msp.add_line(
            (-x_low, y_low),
            (-x_high_ext, y_high_ext),
            dxfattribs={"layer": LAYER_ANGLED_LINES},
        )

        BOX_HALF_WIDTH = 353.0   # horizontal ± distance from intersection
        BOX_HEIGHT = 400.0       # vertical projection along Y

        # ---------- Ticks at every intersection with the angled lines ----------

        for leg_type, y in y_variant_map.items():
            # Only consider lines between the lowest and highest
            if not (min(y_low, y_high) <= y <= max(y_low, y_high)):
                continue

            # Intersection with positive angled line at this y
            t = (y - y_low) / dy
            x_pos = x_low + dx * t

            # Mirrored negative x
            x_center_neg = -x_pos

            # Get this leg_type's square half-diagonal
            df_leg = df_for_tower[df_for_tower["Leg Type"] == leg_type]
            if df_leg.empty or col_sq_half not in df_leg.columns:
                continue

            half_diag = parse_distance(df_leg.iloc[0][col_sq_half])
            if half_diag is None:
                continue

            # Layer for this variant = layer of its horizontal line
            offset_value = parse_offset_value(leg_type)
            layer_tick = LAYER_OFFSET_VARIANTS if offset_value is not None else LAYER_BASE_VARIANTS

            # Common vertical positions for ticks
            y_bottom = y - 100
            y_top = y + 100

            # ===== Negative side goalpost =====
            x1_neg = x_center_neg - half_diag
            x2_neg = x_center_neg + half_diag

            msp.add_line(
                (x1_neg, y_bottom),
                (x1_neg, y_top),
                dxfattribs={"layer": layer_tick},
            )
            msp.add_line(
                (x2_neg, y_bottom),
                (x2_neg, y_top),
                dxfattribs={"layer": layer_tick},
            )
            msp.add_line(
                (x1_neg, y_top),
                (x2_neg, y_top),
                dxfattribs={"layer": layer_tick},
            )

            # ===== Positive side goalpost =====
            x_center_pos = x_pos
            x1_pos = x_center_pos - half_diag
            x2_pos = x_center_pos + half_diag

            msp.add_line(
                (x1_pos, y_bottom),
                (x1_pos, y_top),
                dxfattribs={"layer": layer_tick},
            )
            msp.add_line(
                (x2_pos, y_bottom),
                (x2_pos, y_top),
                dxfattribs={"layer": layer_tick},
            )
            msp.add_line(
                (x1_pos, y_top),
                (x2_pos, y_top),
                dxfattribs={"layer": layer_tick},
            )

        # ---------- Angled box on every BASE_VARIANTS horizontal line ----------

    # ---------- Angled box on every BASE_VARIANTS horizontal line ----------

    for leg_type, y in y_variant_map.items():
        # Only consider base variants (no /+offset)
        if parse_offset_value(leg_type) is not None:
            continue

        # Only if the angled line actually crosses this y
        if not (min(y_low, y_high) <= y <= max(y_low, y_high)):
            continue

        # Intersection of the positive angled line with this horizontal
        t_box = (y - y_low) / dy
        x_pos_box = x_low + dx * t_box   # positive side intersection

        # Common vertical geometry for the box
        y_base_box = y + 100.0           # start 100 units above the horizontal line
        dy_box = BOX_HEIGHT              # 400 units vertical projection
        t_height = dy_box / dy
        y_top_box = y_base_box + dy_box

        # All box lines live in BASE_VARIANTS
        box_layer = LAYER_BASE_VARIANTS

        # ===== NEGATIVE SIDE BOX =====
        x_neg_center = -x_pos_box        # mirrored negative side intersection

        # Step BOX_HALF_WIDTH horizontally left/right from that intersection
        x_left_neg = x_neg_center - BOX_HALF_WIDTH
        x_right_neg = x_neg_center + BOX_HALF_WIDTH

        # Go up along the slope of the NEGATIVE angled line: direction (-dx, dy)
        delta_x_neg = -dx * t_height     # horizontal shift along that slope

        # Top points of the two slanted lines (negative side)
        x_left_neg_top = x_left_neg + delta_x_neg
        x_right_neg_top = x_right_neg + delta_x_neg

        # Left slanted side (negative)
        msp.add_line(
            (x_left_neg, y_base_box),
            (x_left_neg_top, y_top_box),
            dxfattribs={"layer": box_layer},
        )

        # Right slanted side (negative)
        msp.add_line(
            (x_right_neg, y_base_box),
            (x_right_neg_top, y_top_box),
            dxfattribs={"layer": box_layer},
        )

        # Horizontal top (negative)
        msp.add_line(
            (x_left_neg_top, y_top_box),
            (x_right_neg_top, y_top_box),
            dxfattribs={"layer": box_layer},
        )

        # ===== POSITIVE SIDE BOX (MIRRORED) =====
        x_pos_center = x_pos_box        # positive side intersection

        x_left_pos = x_pos_center - BOX_HALF_WIDTH
        x_right_pos = x_pos_center + BOX_HALF_WIDTH

        # Go up along the slope of the POSITIVE angled line: direction (dx, dy)
        delta_x_pos = dx * t_height

        x_left_pos_top = x_left_pos + delta_x_pos
        x_right_pos_top = x_right_pos + delta_x_pos

        # Left slanted side (positive)
        msp.add_line(
            (x_left_pos, y_base_box),
            (x_left_pos_top, y_top_box),
            dxfattribs={"layer": box_layer},
        )

        # Right slanted side (positive)
        msp.add_line(
            (x_right_pos, y_base_box),
            (x_right_pos_top, y_top_box),
            dxfattribs={"layer": box_layer},
        )

        # Horizontal top (positive)
        msp.add_line(
            (x_left_pos_top, y_top_box),
            (x_right_pos_top, y_top_box),
            dxfattribs={"layer": box_layer},
        )


    # ---------- Centerline ----------

    # Dashed vertical centerline at x=0 (on CENTERLINE layer)
    centerline_top = y_max + 1000
    centerline_bottom = y_min - 1000
    msp.add_line(
        (0, centerline_bottom),
        (0, centerline_top),
        dxfattribs={
            "layer": LAYER_CENTERLINE,
            "linetype": "CENTER",  # relies on ezdxf.new(setup=True)
        },
    )

    # ---------- Title ----------

    # Title somewhere up top (above the highest line), on ANNOTATIONS layer
    title_y = y_max + 2000  # some margin above the highest line
    title = f"Tower Type {tower_name}"
    title_text = msp.add_text(
        title,
        dxfattribs={
            "height": TITLE_HEIGHT,
            "layer": LAYER_ANNOTATIONS,
        },
    )
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
