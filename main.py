import math
import pandas as pd
import ezdxf


def create_tower_skeleton_dxf(
    csv_path: str,
    tower_type: str,
    dxf_out: str,
    scale: float = 1000.0,
) -> None:
    """
    Create a 'skeleton' DXF for a given tower type (e.g. 'G5+8') based on diagrams.csv.

    Geometry conventions (similar to your R5+8 skeleton, but slightly simplified):

    - All lengths from the CSV are interpreted in meters and multiplied by `scale`
      to get DXF drawing units (default scale=1000 → mm).
    - The tower has 4 legs, lying on the 4 diagonals at angles:
        45°, 135°, 225°, 315° (counter-clockwise from +X).
    - For each leg type row in the CSV (for that tower type), we draw a leg segment
      on each diagonal, starting at the tower base “corner” and ending at
      radius = `distance on the ground`.
    - We also draw:
        * Outer tower base square (using square half-diagonal)
        * Inner 'styliskos' square (using styliskos half-diagonal)
        * Two reference axes (X and Y)
    """
    # ----------------------------------------------------------------------
    # 1. Load and filter CSV
    # ----------------------------------------------------------------------
    
    #csv_path="diagrams.csv"
    
    df = pd.read_csv(csv_path)
    df_tower = df[df["Tower Type"] == tower_type].copy()

    if df_tower.empty:
        raise ValueError(f"No rows found for Tower Type = {tower_type!r}")

    # We'll assume these are constant within a given tower type:
    row0 = df_tower.iloc[0]
    square_side_m = float(row0["Square Side"])
    square_half_diag_m = float(row0["square half-diagonal"])
    styliskos_half_diag_m = float(row0["styliskos half-diagonal"])

    # Convert to drawing units (e.g. mm)
    square_side = square_side_m * scale
    square_half_diag = square_half_diag_m * scale
    styliskos_half_diag = styliskos_half_diag_m * scale

    # ----------------------------------------------------------------------
    # 2. Create DXF document & layers
    # ----------------------------------------------------------------------
    doc = ezdxf.new("R2010")
    doc.layers.new(name="axes", dxfattribs={"color": 8})
    doc.layers.new(name="tower", dxfattribs={"color": 7})
    doc.layers.new(name="styliskos", dxfattribs={"color": 3})
    doc.layers.new(name="legs", dxfattribs={"color": 1})
    doc.layers.new(name="leg_labels", dxfattribs={"color": 2})

    msp = doc.modelspace()

    # ----------------------------------------------------------------------
    # 3. Draw reference axes
    # ----------------------------------------------------------------------
    axis_len = square_half_diag * 12  # arbitrary nice big length
    msp.add_line((-axis_len, 0), (axis_len, 0), dxfattribs={"layer": "axes"})
    msp.add_line((0, -axis_len), (0, axis_len), dxfattribs={"layer": "axes"})

    # ----------------------------------------------------------------------
    # 4. Draw tower base square
    #
    # The square is centered at (0,0), not rotated, with side: square_side.
    # This ensures the distance from center to each corner equals
    # the 'square half-diagonal' from the CSV.
    # ----------------------------------------------------------------------
    half_side = square_side / 2.0
    tower_pts = [
        (half_side, half_side),
        (-half_side, half_side),
        (-half_side, -half_side),
        (half_side, -half_side),
    ]
    # Close the loop:
    tower_pts.append(tower_pts[0])

    for p1, p2 in zip(tower_pts, tower_pts[1:]):
        msp.add_line(p1, p2, dxfattribs={"layer": "tower"})

    # ----------------------------------------------------------------------
    # 5. Draw styliskos (inner square)
    #
    # Here we match your R5+8 logic more closely: we use the half-diagonal
    # and place the 4 corners on the diagonals:
    #   angles = 45°, 135°, 225°, 315°
    # ----------------------------------------------------------------------
    styl_angles_deg = [45, 135, 225, 315]
    styl_pts = []
    for ang_deg in styl_angles_deg:
        ang = math.radians(ang_deg)
        x = styliskos_half_diag * math.cos(ang)
        y = styliskos_half_diag * math.sin(ang)
        styl_pts.append((x, y))
    styl_pts.append(styl_pts[0])

    for p1, p2 in zip(styl_pts, styl_pts[1:]):
        msp.add_line(p1, p2, dxfattribs={"layer": "styliskos"})

    # ----------------------------------------------------------------------
    # 6. Draw all leg positions for this tower type
    #
    # We use four diagonals, same as the styliskos corners:
    #   45°, 135°, 225°, 315°
    # For each leg type (row in df_tower), we:
    #   - read 'distance on the ground'
    #   - draw 4 leg segments (one on each diagonal), starting at the
    #     tower-corner radius and ending at the leg-foot radius.
    #
    # Tower corner radius (from center to corner) is square_half_diag,
    # which must equal square_side / sqrt(2). We use the CSV value directly.
    # ----------------------------------------------------------------------
    leg_angles_deg = [45, 135, 225, 315]
    tower_corner_radius = square_half_diag

    # We'll also place labels out to the right side (for leg types)
    # so you can see the legend of which leg types are present.
    label_x = tower_corner_radius + (square_side * 4.0)
    label_y_step = square_side * 0.7
    label_y_start = square_side * 4.0

    for i, (_, row) in enumerate(df_tower.iterrows()):
        leg_type = str(row["Leg Type"])
        dist_ground_m = float(row["distance on the ground"])
        leg_radius = dist_ground_m * scale

        # Draw 4 leg segments
        for ang_deg in leg_angles_deg:
            ang = math.radians(ang_deg)
            # Start at tower corner radius along this diagonal
            x0 = tower_corner_radius * math.cos(ang)
            y0 = tower_corner_radius * math.sin(ang)
            # End at leg radius
            x1 = leg_radius * math.cos(ang)
            y1 = leg_radius * math.sin(ang)

            msp.add_line(
                (x0, y0),
                (x1, y1),
                dxfattribs={"layer": "legs"},
            )

        # Add a label for this leg type on the right, stacked vertically
        y_label = label_y_start - i * label_y_step
        msp.add_text(
            f"{leg_type}  ({dist_ground_m:.3f} m)",
            dxfattribs={
                "height": square_side * 0.15,
                "layer": "leg_labels",
            },
        ).set_pos((label_x, y_label))

    # ----------------------------------------------------------------------
    # 7. Add a title
    # ----------------------------------------------------------------------
    title_text = f"Σκέλη {tower_type}"
    msp.add_text(
        title_text,
        dxfattribs={
            "height": square_side * 0.2,
            "layer": "leg_labels",
        },
    ).set_pos((-square_side * 1.5, label_y_start + square_side * 0.5))

    # ----------------------------------------------------------------------
    # 8. Save DXF
    # ----------------------------------------------------------------------
    doc.saveas(dxf_out)
    print(f"DXF saved to: {dxf_out}")


if __name__ == "__main__":
    # Example usage:
    # Adjust these paths as needed.
    csv_file = "diagrams.csv"        # path to your diagrams.csv
    output_dxf = "G5+8_skeli.dxf"    # output DXF file
    create_tower_skeleton_dxf(csv_file, "G5+8", output_dxf)
