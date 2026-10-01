import math

import bpy
import bmesh

from bpy.types import (
    Panel,
    Operator,
    PropertyGroup,
)

from bpy.props import (
    PointerProperty,
    FloatProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    EnumProperty,
)


# ============================================================
# CONSTANTS
# ============================================================

# 1 Blender Unit = 1 meter.
BLENDER_UNIT_IN_METERS = 1.0

VIS_COLLECTION_NAME = "Breast Volume Visualization"


# ============================================================
# MODEL REFERENCE VALUES
# ============================================================

BREAST_DENSITY_G_CM3 = 0.95

GLANDULAR_FRACTION_DEFAULT = 0.301

MATERNAL_BREAST_MULTIPLIER_DEFAULT = 1.45
MATERNAL_GLANDULAR_MULTIPLIER_DEFAULT = 2.385

REFERENCE_BREAST_VOLUME_DEFAULT = 420.0

REFERENCE_STORAGE_DEFAULT = 209.9
REFERENCE_PRODUCTION_DEFAULT = 453.6

MILK_DENSITY_DEFAULT = 1.03


# ============================================================
# TEMPORARY CALCULATION CACHE
# ============================================================

# This only stores the evaluated surface used by the most
# recent calculation, so visualization copies use exactly the
# same geometry that was measured.

CALC_CACHE = {
    "source_name": None,
    "source_pointer": None,

    "surface_vertices": None,
    "surface_faces": None,
}


def clear_calculation_cache():

    CALC_CACHE["source_name"] = None
    CALC_CACHE["source_pointer"] = None

    CALC_CACHE["surface_vertices"] = None
    CALC_CACHE["surface_faces"] = None


# ============================================================
# PROPERTY HELPERS
# ============================================================

def poll_mesh_object(self, obj):

    return obj.type == 'MESH'


# ============================================================
# SETTINGS / RESULTS
# ============================================================

class LEWD_CALC_Properties(PropertyGroup):

    # ========================================================
    # INPUT
    # ========================================================

    source_mesh: PointerProperty(
        name="Source Mesh",
        description="Mesh object to use for the calculation",
        type=bpy.types.Object,
        poll=poll_mesh_object,
    )


    # ========================================================
    # MODEL PARAMETERS
    # ========================================================

    breast_density: FloatProperty(
        name="Breast Density",
        description="Average breast tissue density in g/cm³",
        default=BREAST_DENSITY_G_CM3,
        min=0.0,
        soft_max=2.0,
        precision=4,
    )

    glandular_fraction: FloatProperty(
        name="Glandular Fraction",
        description="Fraction of breast volume modeled as glandular tissue",
        default=GLANDULAR_FRACTION_DEFAULT,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        precision=3,
    )

    maternal_breast_multiplier: FloatProperty(
        name="Maternal Breast Volume",
        description="Total breast volume multiplier in the maternal state",
        default=MATERNAL_BREAST_MULTIPLIER_DEFAULT,
        min=0.0,
        soft_max=3.0,
        precision=3,
    )

    maternal_glandular_multiplier: FloatProperty(
        name="Maternal Glandular Volume",
        description="Glandular volume multiplier in the maternal state",
        default=MATERNAL_GLANDULAR_MULTIPLIER_DEFAULT,
        min=0.0,
        soft_max=5.0,
        precision=3,
    )

    reference_breast_volume: FloatProperty(
        name="Reference Breast Volume",
        description="Reference prepregnancy breast volume in cm³",
        default=REFERENCE_BREAST_VOLUME_DEFAULT,
        min=0.0,
        soft_max=5000.0,
        precision=2,
    )

    reference_storage: FloatProperty(
        name="Reference Milk Storage",
        description="Reference maximum stored milk per breast in mL",
        default=REFERENCE_STORAGE_DEFAULT,
        min=0.0,
        soft_max=5000.0,
        precision=2,
    )

    reference_production: FloatProperty(
        name="Reference Milk Production",
        description="Reference milk production per breast per day in g",
        default=REFERENCE_PRODUCTION_DEFAULT,
        min=0.0,
        soft_max=5000.0,
        precision=2,
    )

    milk_density: FloatProperty(
        name="Milk Density",
        description="Milk density in g/cm³",
        default=MILK_DENSITY_DEFAULT,
        min=0.0,
        soft_max=2.0,
        precision=4,
    )


    # ========================================================
    # VISUALIZATION SETTINGS
    # ========================================================

    show_tissue_spheres: BoolProperty(
        name="Tissue Volume Spheres",
        description="Generate fat and glandular volume markers",
        default=True,
    )

    show_breast_copies: BoolProperty(
        name="Breast State Copies",
        description="Generate breast meshes representing calculated states",
        default=True,
    )

    show_milk_containers: BoolProperty(
        name="Milk Volume Containers",
        description="Generate milk storage and production cylinders",
        default=True,
    )


    tissue_sphere_type: EnumProperty(
        name="Tissue Marker Type",
        description="Sphere topology used for tissue volume markers",
        items=[
            (
                'ICO',
                "Icosphere",
                "Uniform triangular sphere"
            ),
            (
                'UV',
                "UV Sphere",
                "Latitude/longitude sphere"
            ),
        ],
        default='ICO',
    )


    ico_subdivisions: IntProperty(
        name="Icosphere Subdivisions",
        description="Resolution of tissue-volume icospheres",
        default=4,
        min=1,
        max=8,
        soft_max=6,
    )

    uv_segments: IntProperty(
        name="UV Sphere Segments",
        description="Horizontal resolution of UV spheres",
        default=64,
        min=8,
        max=512,
    )

    uv_rings: IntProperty(
        name="UV Sphere Rings",
        description="Vertical resolution of UV spheres",
        default=32,
        min=4,
        max=256,
    )

    milk_cylinder_vertices: IntProperty(
        name="Container Sides",
        description="Number of sides on milk-volume cylinders",
        default=64,
        min=8,
        max=256,
    )

    container_ratio: FloatProperty(
        name="Container H/D Ratio",
        description="Height divided by diameter for milk cylinders",
        default=1.5,
        min=0.25,
        max=5.0,
        precision=2,
    )

    smooth_visualizations: BoolProperty(
        name="Smooth Shading",
        description="Smooth-shade generated visualization meshes",
        default=True,
    )


    # ========================================================
    # STATUS
    # ========================================================

    calculation_complete: BoolProperty(
        default=False,
    )

    status_message: StringProperty(
        default="No calculation performed yet.",
    )


    # ========================================================
    # GEOMETRY RESULTS
    # ========================================================

    vertex_count: IntProperty(default=0)
    triangle_count: IntProperty(default=0)

    volume_cm3: FloatProperty(default=0.0)
    volume_liters: FloatProperty(default=0.0)

    surface_area_m2: FloatProperty(default=0.0)

    empty_mass_kg: FloatProperty(default=0.0)


    # ========================================================
    # REFERENCE RESULTS
    # ========================================================

    reference_normal_glandular_cm3: FloatProperty(
        default=0.0
    )

    reference_maternal_glandular_cm3: FloatProperty(
        default=0.0
    )


    # ========================================================
    # BASELINE RESULTS
    # ========================================================

    baseline_glandular_cm3: FloatProperty(
        default=0.0
    )

    baseline_fat_cm3: FloatProperty(
        default=0.0
    )

    baseline_storage_ml: FloatProperty(
        default=0.0
    )

    baseline_storage_mass_kg: FloatProperty(
        default=0.0
    )

    baseline_production_g_day: FloatProperty(
        default=0.0
    )

    baseline_production_ml_day: FloatProperty(
        default=0.0
    )

    baseline_full_volume_cm3: FloatProperty(
        default=0.0
    )

    baseline_full_mass_kg: FloatProperty(
        default=0.0
    )


    # ========================================================
    # MATERNAL RESULTS
    # ========================================================

    maternal_volume_cm3: FloatProperty(
        default=0.0
    )

    maternal_glandular_cm3: FloatProperty(
        default=0.0
    )

    maternal_fat_cm3: FloatProperty(
        default=0.0
    )

    maternal_storage_ml: FloatProperty(
        default=0.0
    )

    maternal_storage_mass_kg: FloatProperty(
        default=0.0
    )

    maternal_production_g_day: FloatProperty(
        default=0.0
    )

    maternal_production_ml_day: FloatProperty(
        default=0.0
    )

    maternal_full_volume_cm3: FloatProperty(
        default=0.0
    )

    maternal_full_mass_kg: FloatProperty(
        default=0.0
    )


# ============================================================
# UNIT CONVERSION
# ============================================================

def cm3_to_bu3(volume_cm3):

    return (
        volume_cm3
        / 1_000_000.0
        / (BLENDER_UNIT_IN_METERS ** 3)
    )


# ============================================================
# SOURCE MESH MEASUREMENT
# ============================================================

def measure_source_mesh(source_obj):
    """
    Evaluates the source object including modifiers, transforms
    it into world space, calculates volume and surface area
    using BMesh, then triangulates the same surface for later
    visualization copies.

    Returns:
        volume_bu3
        surface_area_bu2
        vertices
        faces
    """

    depsgraph = bpy.context.evaluated_depsgraph_get()

    evaluated_obj = source_obj.evaluated_get(
        depsgraph
    )

    source_mesh = evaluated_obj.to_mesh()

    bm = bmesh.new()

    try:

        bm.from_mesh(
            source_mesh
        )

        # ----------------------------------------------------
        # Transform evaluated geometry into world space.
        # This includes object scale.
        # ----------------------------------------------------

        bm.transform(
            evaluated_obj.matrix_world
        )


        # ----------------------------------------------------
        # Merge effectively identical vertices.
        # ----------------------------------------------------

        bmesh.ops.remove_doubles(
            bm,
            verts=bm.verts[:],
            dist=1e-8
        )


        if len(bm.faces) == 0:

            raise RuntimeError(
                "The source mesh contains no faces."
            )


        if len(bm.verts) < 4:

            raise RuntimeError(
                "The source mesh contains fewer than 4 vertices."
            )


        # ----------------------------------------------------
        # Volume requires a closed volume.
        # Reject open / non-manifold geometry.
        # ----------------------------------------------------

        non_manifold_edges = [
            edge
            for edge in bm.edges
            if not edge.is_manifold
        ]


        if non_manifold_edges:

            raise RuntimeError(
                "The source mesh is not closed/manifold. "
                f"Found {len(non_manifold_edges)} "
                "non-manifold or boundary edges."
            )


        # ----------------------------------------------------
        # Ensure consistent face orientation.
        # ----------------------------------------------------

        bmesh.ops.recalc_face_normals(
            bm,
            faces=bm.faces[:]
        )

        bm.normal_update()


        # ====================================================
        # BMESH VOLUME
        # ====================================================

        volume_bu3 = bm.calc_volume(
            signed=False
        )


        if volume_bu3 <= 0:

            raise RuntimeError(
                "The source mesh produced zero volume."
            )


        # ====================================================
        # SURFACE AREA
        # ====================================================

        surface_area_bu2 = sum(
            face.calc_area()
            for face in bm.faces
        )


        # ====================================================
        # TRIANGULATE FOR VISUALIZATION COPIES
        # ====================================================

        bmesh.ops.triangulate(
            bm,
            faces=bm.faces[:]
        )


        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        bm.verts.index_update()
        bm.faces.index_update()


        vertices = [
            (
                vertex.co.x,
                vertex.co.y,
                vertex.co.z
            )
            for vertex in bm.verts
        ]


        faces = [
            tuple(
                vertex.index
                for vertex in face.verts
            )
            for face in bm.faces
        ]


    finally:

        bm.free()

        evaluated_obj.to_mesh_clear()


    return (
        float(volume_bu3),
        float(surface_area_bu2),
        vertices,
        faces,
    )


# ============================================================
# MAIN CALCULATION ENGINE
# ============================================================

def calculate_breast(
    source_obj,
    settings
):

    # ========================================================
    # MEASURE SOURCE
    # ========================================================

    (
        volume_bu3,
        surface_area_bu2,
        vertices,
        faces,
    ) = measure_source_mesh(
        source_obj
    )


    # ========================================================
    # UNIT CONVERSION
    # ========================================================

    volume_m3 = (
        volume_bu3
        * BLENDER_UNIT_IN_METERS ** 3
    )


    volume_cm3 = (
        volume_m3
        * 1_000_000.0
    )


    surface_area_m2 = (
        surface_area_bu2
        * BLENDER_UNIT_IN_METERS ** 2
    )


    # ========================================================
    # PARAMETER VALIDATION
    # ========================================================

    if settings.milk_density <= 0:

        raise RuntimeError(
            "Milk density must be greater than zero."
        )


    if settings.reference_breast_volume <= 0:

        raise RuntimeError(
            "Reference breast volume must be greater than zero."
        )


    if settings.glandular_fraction <= 0:

        raise RuntimeError(
            "Glandular fraction must be greater than zero."
        )


    if settings.maternal_glandular_multiplier <= 0:

        raise RuntimeError(
            "Maternal glandular multiplier must be greater than zero."
        )


    # ========================================================
    # EMPTY BREAST
    # ========================================================

    empty_mass_kg = (
        volume_cm3
        * settings.breast_density
        / 1000.0
    )


    # ========================================================
    # REFERENCE GLANDULAR VOLUMES
    # ========================================================

    reference_normal_glandular_cm3 = (
        settings.reference_breast_volume
        * settings.glandular_fraction
    )


    reference_maternal_glandular_cm3 = (
        reference_normal_glandular_cm3
        * settings.maternal_glandular_multiplier
    )


    # ========================================================
    # BASELINE
    # ========================================================

    baseline_glandular_cm3 = (
        volume_cm3
        * settings.glandular_fraction
    )


    baseline_fat_cm3 = (
        volume_cm3
        - baseline_glandular_cm3
    )


    baseline_storage_ml = (
        baseline_glandular_cm3
        / reference_maternal_glandular_cm3
        * settings.reference_storage
    )


    baseline_storage_mass_kg = (
        baseline_storage_ml
        * settings.milk_density
        / 1000.0
    )


    baseline_production_g_day = (
        baseline_glandular_cm3
        / reference_maternal_glandular_cm3
        * settings.reference_production
    )


    baseline_production_ml_day = (
        baseline_production_g_day
        / settings.milk_density
    )


    baseline_full_volume_cm3 = (
        volume_cm3
        + baseline_storage_ml
    )


    baseline_full_mass_kg = (
        empty_mass_kg
        + baseline_storage_mass_kg
    )


    # ========================================================
    # MATERNAL
    # ========================================================

    maternal_volume_cm3 = (
        volume_cm3
        * settings.maternal_breast_multiplier
    )


    maternal_glandular_cm3 = (
        baseline_glandular_cm3
        * settings.maternal_glandular_multiplier
    )


    maternal_fat_cm3 = (
        maternal_volume_cm3
        - maternal_glandular_cm3
    )


    maternal_mass_kg = (
        maternal_volume_cm3
        * settings.breast_density
        / 1000.0
    )


    maternal_storage_ml = (
        maternal_glandular_cm3
        / reference_maternal_glandular_cm3
        * settings.reference_storage
    )


    maternal_storage_mass_kg = (
        maternal_storage_ml
        * settings.milk_density
        / 1000.0
    )


    maternal_production_g_day = (
        maternal_glandular_cm3
        / reference_maternal_glandular_cm3
        * settings.reference_production
    )


    maternal_production_ml_day = (
        maternal_production_g_day
        / settings.milk_density
    )


    maternal_full_volume_cm3 = (
        maternal_volume_cm3
        + maternal_storage_ml
    )


    maternal_full_mass_kg = (
        maternal_mass_kg
        + maternal_storage_mass_kg
    )


    # ========================================================
    # RETURN RESULTS
    # ========================================================

    return {

        # ----------------------------------------------------
        # Geometry
        # ----------------------------------------------------

        "vertex_count":
            len(vertices),

        "triangle_count":
            len(faces),

        "volume_cm3":
            volume_cm3,

        "surface_area_m2":
            surface_area_m2,

        "empty_mass_kg":
            empty_mass_kg,


        # ----------------------------------------------------
        # Reference
        # ----------------------------------------------------

        "reference_normal_glandular_cm3":
            reference_normal_glandular_cm3,

        "reference_maternal_glandular_cm3":
            reference_maternal_glandular_cm3,


        # ----------------------------------------------------
        # Baseline
        # ----------------------------------------------------

        "baseline": {

            "glandular_cm3":
                baseline_glandular_cm3,

            "fat_cm3":
                baseline_fat_cm3,

            "storage_ml":
                baseline_storage_ml,

            "storage_mass_kg":
                baseline_storage_mass_kg,

            "production_g_day":
                baseline_production_g_day,

            "production_ml_day":
                baseline_production_ml_day,

            "full_volume_cm3":
                baseline_full_volume_cm3,

            "full_mass_kg":
                baseline_full_mass_kg,
        },


        # ----------------------------------------------------
        # Maternal
        # ----------------------------------------------------

        "maternal": {

            "volume_cm3":
                maternal_volume_cm3,

            "glandular_cm3":
                maternal_glandular_cm3,

            "fat_cm3":
                maternal_fat_cm3,

            "storage_ml":
                maternal_storage_ml,

            "storage_mass_kg":
                maternal_storage_mass_kg,

            "production_g_day":
                maternal_production_g_day,

            "production_ml_day":
                maternal_production_ml_day,

            "full_volume_cm3":
                maternal_full_volume_cm3,

            "full_mass_kg":
                maternal_full_mass_kg,
        },


        # ----------------------------------------------------
        # Cached evaluated surface
        # ----------------------------------------------------

        "surface_vertices":
            vertices,

        "surface_faces":
            faces,
    }


# ============================================================
# STORE RESULTS
# ============================================================

def store_results(
    settings,
    results
):

    # ========================================================
    # GEOMETRY
    # ========================================================

    settings.vertex_count = (
        results["vertex_count"]
    )

    settings.triangle_count = (
        results["triangle_count"]
    )

    settings.volume_cm3 = (
        results["volume_cm3"]
    )

    settings.volume_liters = (
        results["volume_cm3"]
        / 1000.0
    )

    settings.surface_area_m2 = (
        results["surface_area_m2"]
    )

    settings.empty_mass_kg = (
        results["empty_mass_kg"]
    )


    # ========================================================
    # REFERENCE
    # ========================================================

    settings.reference_normal_glandular_cm3 = (
        results[
            "reference_normal_glandular_cm3"
        ]
    )

    settings.reference_maternal_glandular_cm3 = (
        results[
            "reference_maternal_glandular_cm3"
        ]
    )


    # ========================================================
    # BASELINE
    # ========================================================

    baseline = (
        results["baseline"]
    )

    settings.baseline_glandular_cm3 = (
        baseline["glandular_cm3"]
    )

    settings.baseline_fat_cm3 = (
        baseline["fat_cm3"]
    )

    settings.baseline_storage_ml = (
        baseline["storage_ml"]
    )

    settings.baseline_storage_mass_kg = (
        baseline["storage_mass_kg"]
    )

    settings.baseline_production_g_day = (
        baseline["production_g_day"]
    )

    settings.baseline_production_ml_day = (
        baseline["production_ml_day"]
    )

    settings.baseline_full_volume_cm3 = (
        baseline["full_volume_cm3"]
    )

    settings.baseline_full_mass_kg = (
        baseline["full_mass_kg"]
    )


    # ========================================================
    # MATERNAL
    # ========================================================

    maternal = (
        results["maternal"]
    )

    settings.maternal_volume_cm3 = (
        maternal["volume_cm3"]
    )

    settings.maternal_glandular_cm3 = (
        maternal["glandular_cm3"]
    )

    settings.maternal_fat_cm3 = (
        maternal["fat_cm3"]
    )

    settings.maternal_storage_ml = (
        maternal["storage_ml"]
    )

    settings.maternal_storage_mass_kg = (
        maternal["storage_mass_kg"]
    )

    settings.maternal_production_g_day = (
        maternal["production_g_day"]
    )

    settings.maternal_production_ml_day = (
        maternal["production_ml_day"]
    )

    settings.maternal_full_volume_cm3 = (
        maternal["full_volume_cm3"]
    )

    settings.maternal_full_mass_kg = (
        maternal["full_mass_kg"]
    )


# ============================================================
# VISUALIZATION COLLECTION
# ============================================================

def clear_visualization_collection():

    collection = bpy.data.collections.get(
        VIS_COLLECTION_NAME
    )


    if collection is None:

        return


    for obj in list(
        collection.objects
    ):

        mesh = (
            obj.data
            if obj.type == 'MESH'
            else None
        )


        bpy.data.objects.remove(
            obj,
            do_unlink=True
        )


        if (
            mesh is not None
            and mesh.users == 0
        ):

            bpy.data.meshes.remove(
                mesh
            )


    bpy.data.collections.remove(
        collection
    )


def create_visualization_collection(
    scene
):

    clear_visualization_collection()


    collection = (
        bpy.data.collections.new(
            VIS_COLLECTION_NAME
        )
    )


    scene.collection.children.link(
        collection
    )


    return collection


# ============================================================
# GENERIC MESH CREATION
# ============================================================

def create_mesh_object(
    name,
    vertices,
    edges,
    faces,
    collection,
):

    mesh = bpy.data.meshes.new(
        name + "_Mesh"
    )


    mesh.from_pydata(
        vertices,
        edges,
        faces
    )


    mesh.update()


    obj = bpy.data.objects.new(
        name,
        mesh
    )


    collection.objects.link(
        obj
    )


    return obj


# ============================================================
# SMOOTH SHADING
# ============================================================

def smooth_object(
    obj,
    enabled=True
):

    if not enabled:

        return


    if obj.type != 'MESH':

        return


    for polygon in obj.data.polygons:

        polygon.use_smooth = True


def smooth_cylinder_sides(
    obj,
    enabled=True
):

    if not enabled:

        return


    for polygon in obj.data.polygons:

        # Quad faces are the cylinder walls.
        # Caps remain flat shaded.

        if len(
            polygon.vertices
        ) == 4:

            polygon.use_smooth = True


# ============================================================
# EXACT-VOLUME TISSUE SPHERE
# ============================================================

def create_exact_volume_sphere(
    name,
    target_volume_cm3,
    location,
    settings,
    collection,
):

    if target_volume_cm3 <= 0:

        return None


    target_volume_bu3 = (
        cm3_to_bu3(
            target_volume_cm3
        )
    )


    bm = bmesh.new()


    try:

        # ----------------------------------------------------
        # Create unit primitive.
        # ----------------------------------------------------

        if settings.tissue_sphere_type == 'ICO':

            bmesh.ops.create_icosphere(
                bm,
                subdivisions=settings.ico_subdivisions,
                radius=1.0,
            )


        else:

            bmesh.ops.create_uvsphere(
                bm,
                u_segments=settings.uv_segments,
                v_segments=settings.uv_rings,
                radius=1.0,
            )


        # ----------------------------------------------------
        # Measure actual polygon volume.
        # ----------------------------------------------------

        actual_volume = (
            bm.calc_volume(
                signed=False
            )
        )


        if actual_volume <= 0:

            raise RuntimeError(
                f"Could not calculate volume of {name}."
            )


        # ----------------------------------------------------
        # Exact volume correction.
        #
        # Volume changes with linear scale³.
        # ----------------------------------------------------

        scale_factor = (
            target_volume_bu3
            / actual_volume
        ) ** (1.0 / 3.0)


        for vertex in bm.verts:

            vertex.co *= (
                scale_factor
            )


        # ----------------------------------------------------
        # Convert to Blender mesh.
        # ----------------------------------------------------

        mesh = bpy.data.meshes.new(
            name + "_Mesh"
        )


        bm.to_mesh(
            mesh
        )


    finally:

        bm.free()


    obj = bpy.data.objects.new(
        name,
        mesh
    )


    collection.objects.link(
        obj
    )


    obj.location = (
        location
    )


    smooth_object(
        obj,
        settings.smooth_visualizations
    )


    obj["target_volume_cm3"] = (
        float(
            target_volume_cm3
        )
    )


    obj["visualization_type"] = (
        "Tissue Volume"
    )


    return obj


# ============================================================
# BREAST STATE COPY
# ============================================================

def create_breast_state_copy(
    name,
    source_vertices,
    source_faces,
    original_volume_cm3,
    target_volume_cm3,
    source_center,
    location,
    smooth,
    collection,
):

    if original_volume_cm3 <= 0:

        raise RuntimeError(
            "Original breast volume must be greater than zero."
        )


    if target_volume_cm3 <= 0:

        return None


    # --------------------------------------------------------
    # Uniform scale required to achieve target volume.
    # --------------------------------------------------------

    scale_factor = (
        target_volume_cm3
        / original_volume_cm3
    ) ** (1.0 / 3.0)


    cx, cy, cz = (
        source_center
    )


    scaled_vertices = []


    for vertex in source_vertices:

        x = (
            vertex[0] - cx
        )

        y = (
            vertex[1] - cy
        )

        z = (
            vertex[2] - cz
        )


        scaled_vertices.append(
            (
                x * scale_factor,
                y * scale_factor,
                z * scale_factor,
            )
        )


    obj = create_mesh_object(
        name,
        scaled_vertices,
        [],
        source_faces,
        collection,
    )


    obj.location = (
        location
    )


    smooth_object(
        obj,
        smooth
    )


    obj["target_volume_cm3"] = (
        float(
            target_volume_cm3
        )
    )


    obj["volume_scale"] = (
        float(
            scale_factor
        )
    )


    obj["visualization_type"] = (
        "Breast State"
    )


    return obj


# ============================================================
# MILK CYLINDER
# ============================================================

def create_milk_cylinder(
    name,
    target_volume_ml,
    location,
    settings,
    collection,
):

    if target_volume_ml <= 0:

        return None


    # 1 mL = 1 cm³.

    target_volume_bu3 = (
        cm3_to_bu3(
            target_volume_ml
        )
    )


    sides = max(
        3,
        settings.milk_cylinder_vertices
    )


    ratio = (
        settings.container_ratio
    )


    if ratio <= 0:

        raise RuntimeError(
            "Container H/D ratio must be greater than zero."
        )


    # --------------------------------------------------------
    # Exact N-gon cylinder dimensions.
    #
    # Base area:
    #
    # A = N/2 * r² * sin(2π/N)
    #
    # h = ratio * diameter
    #   = 2 * ratio * r
    #
    # Therefore:
    #
    # V = N * ratio * r³ * sin(2π/N)
    # --------------------------------------------------------

    polygon_factor = (
        sides
        * ratio
        * math.sin(
            2.0
            * math.pi
            / sides
        )
    )


    radius = (
        target_volume_bu3
        / polygon_factor
    ) ** (1.0 / 3.0)


    diameter = (
        radius * 2.0
    )


    height = (
        ratio
        * diameter
    )


    bm = bmesh.new()


    try:

        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=sides,
            radius1=radius,
            radius2=radius,
            depth=height,
        )


        mesh = bpy.data.meshes.new(
            name + "_Mesh"
        )


        bm.to_mesh(
            mesh
        )


    finally:

        bm.free()


    obj = bpy.data.objects.new(
        name,
        mesh
    )


    collection.objects.link(
        obj
    )


    obj.location = (
        location
    )


    smooth_cylinder_sides(
        obj,
        settings.smooth_visualizations
    )


    obj["target_volume_ml"] = (
        float(
            target_volume_ml
        )
    )


    obj["visualization_type"] = (
        "Milk Volume"
    )


    return obj


# ============================================================
# VISUALIZATION LAYOUT
# ============================================================

def get_visualization_layout(
    surface_vertices
):

    if not surface_vertices:

        raise RuntimeError(
            "No cached source vertices are available."
        )


    min_x = min(
        vertex[0]
        for vertex in surface_vertices
    )

    min_y = min(
        vertex[1]
        for vertex in surface_vertices
    )

    min_z = min(
        vertex[2]
        for vertex in surface_vertices
    )


    max_x = max(
        vertex[0]
        for vertex in surface_vertices
    )

    max_y = max(
        vertex[1]
        for vertex in surface_vertices
    )

    max_z = max(
        vertex[2]
        for vertex in surface_vertices
    )


    center = (
        (min_x + max_x) / 2.0,
        (min_y + max_y) / 2.0,
        (min_z + max_z) / 2.0,
    )


    dimension_x = (
        max_x - min_x
    )

    dimension_y = (
        max_y - min_y
    )

    dimension_z = (
        max_z - min_z
    )


    largest_dimension = max(
        dimension_x,
        dimension_y,
        dimension_z,
        0.05,
    )


    spacing = (
        largest_dimension
        * 1.75
    )


    return (
        center,
        spacing
    )


# ============================================================
# CREATE VISUALIZATION OPERATOR
# ============================================================

class LEWD_CALC_OT_create_visualization(
    Operator
):

    bl_idname = (
        "lewdcalc.create_visualization"
    )

    bl_label = (
        "Create Visualization"
    )

    bl_description = (
        "Generate visualization meshes from "
        "the latest calculation"
    )


    def execute(
        self,
        context
    ):

        settings = (
            context.scene.lewd_calc
        )


        source_obj = (
            settings.source_mesh
        )


        # ====================================================
        # VALIDATION
        # ====================================================

        if not settings.calculation_complete:

            self.report(
                {'ERROR'},
                "Run Calculate first."
            )

            return {'CANCELLED'}


        if source_obj is None:

            self.report(
                {'ERROR'},
                "The source mesh is missing."
            )

            return {'CANCELLED'}


        if (
            CALC_CACHE["surface_vertices"]
            is None
        ):

            self.report(
                {'ERROR'},
                "Calculation cache is empty. "
                "Run Calculate again."
            )

            return {'CANCELLED'}


        if (
            CALC_CACHE["source_pointer"]
            != source_obj.as_pointer()
        ):

            self.report(
                {'ERROR'},
                "The source mesh changed. "
                "Run Calculate again."
            )

            return {'CANCELLED'}


        if not any(
            (
                settings.show_tissue_spheres,
                settings.show_breast_copies,
                settings.show_milk_containers,
            )
        ):

            self.report(
                {'WARNING'},
                "No visualization types are enabled."
            )

            return {'CANCELLED'}


        surface_vertices = (
            CALC_CACHE[
                "surface_vertices"
            ]
        )


        surface_faces = (
            CALC_CACHE[
                "surface_faces"
            ]
        )


        # ====================================================
        # GENERATE
        # ====================================================

        try:

            collection = (
                create_visualization_collection(
                    context.scene
                )
            )


            (
                source_center,
                spacing,
            ) = (
                get_visualization_layout(
                    surface_vertices
                )
            )


            cx, cy, cz = (
                source_center
            )


            # =================================================
            # TISSUE VOLUMES
            #
            # Upper row.
            # =================================================

            if settings.show_tissue_spheres:

                tissue_data = (

                    (
                        "LVT_Baseline_Fat",
                        settings.baseline_fat_cm3,
                    ),

                    (
                        "LVT_Baseline_Glandular",
                        settings.baseline_glandular_cm3,
                    ),

                    (
                        "LVT_Maternal_Fat",
                        settings.maternal_fat_cm3,
                    ),

                    (
                        "LVT_Maternal_Glandular",
                        settings.maternal_glandular_cm3,
                    ),
                )


                for index, (
                    name,
                    volume,
                ) in enumerate(
                    tissue_data
                ):

                    location = (
                        cx + spacing * (index + 1),
                        cy + spacing,
                        cz,
                    )


                    create_exact_volume_sphere(
                        name,
                        volume,
                        location,
                        settings,
                        collection,
                    )


            # =================================================
            # BREAST STATE COPIES
            #
            # Middle row.
            # =================================================

            if settings.show_breast_copies:

                breast_data = (

                    (
                        "LVT_Baseline_Full_Breast",
                        settings.baseline_full_volume_cm3,
                    ),

                    (
                        "LVT_Maternal_Breast",
                        settings.maternal_volume_cm3,
                    ),

                    (
                        "LVT_Maternal_Full_Breast",
                        settings.maternal_full_volume_cm3,
                    ),
                )


                for index, (
                    name,
                    target_volume,
                ) in enumerate(
                    breast_data
                ):

                    location = (
                        cx + spacing * (index + 1),
                        cy,
                        cz,
                    )


                    create_breast_state_copy(
                        name=name,

                        source_vertices=
                            surface_vertices,

                        source_faces=
                            surface_faces,

                        original_volume_cm3=
                            settings.volume_cm3,

                        target_volume_cm3=
                            target_volume,

                        source_center=
                            source_center,

                        location=
                            location,

                        smooth=
                            settings.smooth_visualizations,

                        collection=
                            collection,
                    )


            # =================================================
            # MILK VOLUMES
            #
            # Lower row.
            # =================================================

            if settings.show_milk_containers:

                milk_data = (

                    (
                        "LVT_Baseline_Milk_Storage",
                        settings.baseline_storage_ml,
                    ),

                    (
                        "LVT_Maternal_Milk_Storage",
                        settings.maternal_storage_ml,
                    ),

                    (
                        "LVT_Baseline_Daily_Production",
                        settings.baseline_production_ml_day,
                    ),

                    (
                        "LVT_Maternal_Daily_Production",
                        settings.maternal_production_ml_day,
                    ),
                )


                for index, (
                    name,
                    volume,
                ) in enumerate(
                    milk_data
                ):

                    location = (
                        cx + spacing * (index + 1),
                        cy - spacing,
                        cz,
                    )


                    create_milk_cylinder(
                        name,
                        volume,
                        location,
                        settings,
                        collection,
                    )


        except Exception as error:

            clear_visualization_collection()


            self.report(
                {'ERROR'},
                f"Visualization failed: {error}"
            )


            return {'CANCELLED'}


        self.report(
            {'INFO'},
            "Visualization created."
        )


        return {'FINISHED'}


# ============================================================
# CLEAR VISUALIZATION OPERATOR
# ============================================================

class LEWD_CALC_OT_clear_visualization(
    Operator
):

    bl_idname = (
        "lewdcalc.clear_visualization"
    )

    bl_label = (
        "Clear Visualization"
    )

    bl_description = (
        "Delete visualization objects created "
        "by Lewd Volume Tools"
    )


    def execute(
        self,
        context
    ):

        clear_visualization_collection()


        self.report(
            {'INFO'},
            "Visualization cleared."
        )


        return {'FINISHED'}


# ============================================================
# CALCULATE OPERATOR
# ============================================================

class LEWD_CALC_OT_calculate(
    Operator
):

    bl_idname = (
        "lewdcalc.calculate"
    )

    bl_label = (
        "Calculate"
    )

    bl_description = (
        "Calculate breast volume and lactation values"
    )


    def execute(
        self,
        context
    ):

        settings = (
            context.scene.lewd_calc
        )


        source_obj = (
            settings.source_mesh
        )


        if source_obj is None:

            self.report(
                {'ERROR'},
                "Select a source mesh first."
            )

            return {'CANCELLED'}


        try:

            results = (
                calculate_breast(
                    source_obj,
                    settings
                )
            )


            store_results(
                settings,
                results
            )


            # ------------------------------------------------
            # Cache exact evaluated geometry used for
            # the calculation.
            # ------------------------------------------------

            CALC_CACHE["source_name"] = (
                source_obj.name
            )


            CALC_CACHE["source_pointer"] = (
                source_obj.as_pointer()
            )


            CALC_CACHE["surface_vertices"] = [
                tuple(vertex)
                for vertex
                in results["surface_vertices"]
            ]


            CALC_CACHE["surface_faces"] = [
                tuple(face)
                for face
                in results["surface_faces"]
            ]


        except Exception as error:

            clear_calculation_cache()


            settings.calculation_complete = (
                False
            )


            settings.status_message = (
                f"Error: {error}"
            )


            self.report(
                {'ERROR'},
                str(error)
            )


            return {'CANCELLED'}


        settings.calculation_complete = (
            True
        )


        settings.status_message = (
            "Calculation complete."
        )


        self.report(
            {'INFO'},
            "Breast calculation complete."
        )


        return {'FINISHED'}


# ============================================================
# SIDEBAR PANEL
# ============================================================

class LEWD_CALC_PT_main(
    Panel
):

    bl_label = (
        "Lewd Volume Tools"
    )

    bl_idname = (
        "LEWD_CALC_PT_main"
    )

    bl_space_type = (
        'VIEW_3D'
    )

    bl_region_type = (
        'UI'
    )

    bl_category = (
        "Lewd Calculator"
    )


    def draw(
        self,
        context
    ):

        layout = (
            self.layout
        )


        settings = (
            context.scene.lewd_calc
        )


        # ====================================================
        # INPUT
        # ====================================================

        box = layout.box()


        box.label(
            text="Input",
            icon='MESH_DATA'
        )


        box.prop(
            settings,
            "source_mesh"
        )


        box.operator(
            "lewdcalc.calculate",
            text="Calculate"
        )


        # ====================================================
        # MODEL PARAMETERS
        # ====================================================

        box = layout.box()


        box.label(
            text="Model Parameters",
            icon='SETTINGS'
        )


        box.prop(
            settings,
            "breast_density"
        )


        box.prop(
            settings,
            "glandular_fraction"
        )


        box.prop(
            settings,
            "maternal_breast_multiplier"
        )


        box.prop(
            settings,
            "maternal_glandular_multiplier"
        )


        box.separator()


        box.prop(
            settings,
            "reference_breast_volume"
        )


        box.prop(
            settings,
            "reference_storage"
        )


        box.prop(
            settings,
            "reference_production"
        )


        box.prop(
            settings,
            "milk_density"
        )


        # ====================================================
        # VISUALIZATION SETTINGS
        # ====================================================

        box = layout.box()


        box.label(
            text="Visualization Settings"
        )


        box.prop(
            settings,
            "show_tissue_spheres"
        )


        box.prop(
            settings,
            "show_breast_copies"
        )


        box.prop(
            settings,
            "show_milk_containers"
        )


        # ----------------------------------------------------
        # Tissue markers
        # ----------------------------------------------------

        if settings.show_tissue_spheres:

            box.separator()


            box.label(
                text="Tissue Markers"
            )


            box.prop(
                settings,
                "tissue_sphere_type"
            )


            if (
                settings.tissue_sphere_type
                == 'ICO'
            ):

                box.prop(
                    settings,
                    "ico_subdivisions"
                )


            else:

                box.prop(
                    settings,
                    "uv_segments"
                )


                box.prop(
                    settings,
                    "uv_rings"
                )


        # ----------------------------------------------------
        # Milk containers
        # ----------------------------------------------------

        if settings.show_milk_containers:

            box.separator()


            box.label(
                text="Milk Containers"
            )


            box.prop(
                settings,
                "milk_cylinder_vertices"
            )


            box.prop(
                settings,
                "container_ratio"
            )


        box.separator()


        box.prop(
            settings,
            "smooth_visualizations"
        )


        # ----------------------------------------------------
        # Visualization buttons
        # ----------------------------------------------------

        row = box.row()


        row.enabled = (
            settings.calculation_complete
        )


        row.operator(
            "lewdcalc.create_visualization",
            text="Create Visualization"
        )


        box.operator(
            "lewdcalc.clear_visualization",
            text="Clear Visualization"
        )


        # ====================================================
        # RESULTS
        # ====================================================

        box = layout.box()


        box.label(
            text="Results",
            icon='INFO'
        )


        if not settings.calculation_complete:

            box.label(
                text=settings.status_message
            )


        else:

            # =================================================
            # GEOMETRY
            # =================================================

            sub = box.box()


            sub.label(
                text="Original Breast Measurements"
            )


            sub.label(
                text=(
                    f"Breast Volume: "
                    f"{settings.volume_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Breast Capacity: "
                    f"{settings.volume_liters:,.3f} L"
                )
            )


            sub.label(
                text=(
                    f"Breast Surface Area: "
                    f"{settings.surface_area_m2:,.4f} m²"
                )
            )


            sub.label(
                text=(
                    f"Empty (No Milk) Mass: "
                    f"{settings.empty_mass_kg:,.3f} kg"
                )
            )


            sub.label(
                text=(
                    f"Vertices: "
                    f"{settings.vertex_count:,}"
                )
            )


            sub.label(
                text=(
                    f"Triangles: "
                    f"{settings.triangle_count:,}"
                )
            )


            # =================================================
            # REFERENCE
            # =================================================

            sub = box.box()


            sub.label(
                text="Human Female Average Reference"
            )


            sub.label(
                text=(
                    f"Human Female Average Glandular Volume: "
                    f"{settings.reference_normal_glandular_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Human Female Average Maternal Glandular Volume: "
                    f"{settings.reference_maternal_glandular_cm3:,.2f} cm³"
                )
            )


            # =================================================
            # BASELINE
            # =================================================

            sub = box.box()


            sub.label(
                text="Baseline / Regular"
            )


            sub.label(
                text=(
                    f"Glandular Tissue: "
                    f"{settings.baseline_glandular_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Fat Tissue: "
                    f"{settings.baseline_fat_cm3:,.2f} cm³"
                )
            )


            sub.separator()


            sub.label(
                text=(
                    f"Maximum Milk Storage: "
                    f"{settings.baseline_storage_ml:,.2f} mL"
                )
            )


            sub.label(
                text=(
                    f"Stored Milk Mass: "
                    f"{settings.baseline_storage_mass_kg:,.3f} kg"
                )
            )


            sub.separator()


            sub.label(
                text=(
                    f"Daily Milk Production: "
                    f"{settings.baseline_production_g_day:,.2f} g/day"
                )
            )


            sub.label(
                text=(
                    f"Daily Milk Production Volume: "
                    f"{settings.baseline_production_ml_day:,.2f} mL/day"
                )
            )


            sub.separator()


            sub.label(
                text=(
                    f"Maximum Full of Milk Volume: "
                    f"{settings.baseline_full_volume_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Maximum Full Of Milk Mass: "
                    f"{settings.baseline_full_mass_kg:,.3f} kg"
                )
            )


            # =================================================
            # MATERNAL
            # =================================================

            sub = box.box()


            sub.label(
                text="Maternal"
            )


            sub.label(
                text=(
                    f"Breast Volume: "
                    f"{settings.maternal_volume_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Glandular Tissue: "
                    f"{settings.maternal_glandular_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Fat Tissue: "
                    f"{settings.maternal_fat_cm3:,.2f} cm³"
                )
            )


            sub.separator()


            sub.label(
                text=(
                    f"Maximum Milk Storage: "
                    f"{settings.maternal_storage_ml:,.2f} mL"
                )
            )


            sub.label(
                text=(
                    f"Stored Milk Mass: "
                    f"{settings.maternal_storage_mass_kg:,.3f} kg"
                )
            )


            sub.separator()


            sub.label(
                text=(
                    f"Daily Milk Production: "
                    f"{settings.maternal_production_g_day:,.2f} g/day"
                )
            )


            sub.label(
                text=(
                    f"Daily Milk Production Volume: "
                    f"{settings.maternal_production_ml_day:,.2f} mL/day"
                )
            )


            sub.separator()


            sub.label(
                text=(
                    f"Maximum Full Of Milk Volume: "
                    f"{settings.maternal_full_volume_cm3:,.2f} cm³"
                )
            )


            sub.label(
                text=(
                    f"Maximum Full Of Milk Mass: "
                    f"{settings.maternal_full_mass_kg:,.3f} kg"
                )
            )


        # ====================================================
        # STATUS
        # ====================================================

        layout.separator()


        if settings.calculation_complete:

            layout.label(
                text=settings.status_message,
                icon='CHECKMARK'
            )


        else:

            layout.label(
                text=settings.status_message
            )


# ============================================================
# REGISTRATION
# ============================================================

classes = (
    LEWD_CALC_Properties,

    LEWD_CALC_OT_calculate,

    LEWD_CALC_OT_create_visualization,
    LEWD_CALC_OT_clear_visualization,

    LEWD_CALC_PT_main,
)


def register():

    for cls in classes:

        bpy.utils.register_class(
            cls
        )


    bpy.types.Scene.lewd_calc = (
        PointerProperty(
            type=LEWD_CALC_Properties
        )
    )


def unregister():

    clear_calculation_cache()


    if hasattr(
        bpy.types.Scene,
        "lewd_calc"
    ):

        del bpy.types.Scene.lewd_calc


    for cls in reversed(
        classes
    ):

        bpy.utils.unregister_class(
            cls
        )