import os
import re
import uuid

from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
    jsonify,
    send_file
)

from dotenv import load_dotenv
from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)
from werkzeug.utils import secure_filename

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl import load_workbook


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "change-this-secret-key"
)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL haijawekwa kwenye environment variables."
    )


pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=5,
    kwargs={
        "row_factory": dict_row
    }
)


# ============================================================
# UPLOADS
# ============================================================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)


ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}


# ============================================================
# DATABASE CONNECTION HELPERS
# ============================================================

def get_db():
    """
    Gets one PostgreSQL connection from the pool
    and stores it in Flask's application context.
    """

    if "db" not in g:

        db = pool.getconn()

        try:
            db.execute("SELECT 1")

        except Exception:

            try:
                pool.putconn(
                    db,
                    destroy=True
                )
            except Exception:
                pass

            db = pool.getconn()

        g.db = db

    return g.db


@app.teardown_appcontext
def close_db(exception=None):

    db = g.pop("db", None)

    if db is not None:

        try:

            if exception is None:
                db.commit()
            else:
                db.rollback()

            pool.putconn(db)

        except Exception:

            try:
                pool.putconn(
                    db,
                    destroy=True
                )
            except Exception:
                pass


# ============================================================
# FILE HELPERS
# ============================================================

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(
            ".",
            1
        )[1].lower() in ALLOWED_EXTENSIONS
    )


def save_uploaded_image(file):

    if not file:
        return None

    if not file.filename:
        return None

    if not allowed_file(file.filename):
        return None

    original_name = secure_filename(
        file.filename
    )

    extension = (
        original_name
        .rsplit(".", 1)[1]
        .lower()
    )

    filename = (
        f"{uuid.uuid4().hex}.{extension}"
    )

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    file.save(filepath)

    return filename


def delete_uploaded_file(filename):

    if not filename:
        return

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    if os.path.isfile(filepath):

        try:
            os.remove(filepath)
        except OSError:
            pass


# ============================================================
# CHURCH SETTINGS
# ============================================================

def get_church_settings():

    db = get_db()

    settings = db.execute(
        """
        SELECT
            id,
            church_name,
            address,
            phone,
            email,
            logo
        FROM church_settings
        WHERE id = 1
        """
    ).fetchone()

    return settings


# ============================================================
# SUBZONE HELPERS
# ============================================================

def get_active_subzones():

    db = get_db()

    return db.execute(
        """
        SELECT
            id,
            name
        FROM subzones
        WHERE active = 1
        ORDER BY name ASC
        """
    ).fetchall()


def get_all_subzones_with_counts():

    db = get_db()

    return db.execute(
        """
        SELECT
            s.id,
            s.name,
            s.description,
            s.active,
            s.created_at,
            s.updated_at,
            COUNT(w.id) AS member_count
        FROM subzones s
        LEFT JOIN waumini w
            ON w.subzone_id = s.id
        GROUP BY
            s.id,
            s.name,
            s.description,
            s.active,
            s.created_at,
            s.updated_at
        ORDER BY
            s.name ASC
        """
    ).fetchall()


# ============================================================
# REGISTRATION NUMBER
# ============================================================
# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_database():

    db = get_db()

    # Database tables will be initialized here.

def generate_registration_number():

    db = get_db()

    year = datetime.now().year

    prefix = f"WM-{year}-"

    row = db.execute(
        """
        SELECT
            namba_ya_usajili
        FROM waumini
        WHERE namba_ya_usajili LIKE %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"{prefix}%",)
    ).fetchone()

    if not row:

        return f"{prefix}0001"

    last_number = row["namba_ya_usajili"]

    try:

        last_sequence = int(
            last_number.split("-")[-1]
        )

    except (
        ValueError,
        AttributeError
    ):

        last_sequence = 0

    next_sequence = last_sequence + 1

    return (
        f"{prefix}"
        f"{next_sequence:04d}"
    )


# ============================================================
# AUTHENTICATION HELPERS
# ============================================================

    # --------------------------------------------------------
    # GROUPS
    # --------------------------------------------------------

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER
            GENERATED ALWAYS AS IDENTITY
            PRIMARY KEY,

            name TEXT NOT NULL UNIQUE,

            description TEXT,

            leader TEXT,

            phone TEXT,

            is_active BOOLEAN
            NOT NULL DEFAULT TRUE,

            created_at TIMESTAMP
            NOT NULL DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP
            NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # --------------------------------------------------------
    # MEMBER GROUP
    # --------------------------------------------------------

    db.execute(
        """
        ALTER TABLE waumini
        ADD COLUMN IF NOT EXISTS group_id INTEGER
        """
    )

    db.execute(
        """
        DO $$
        BEGIN

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'waumini_group_id_fkey'
            ) THEN

                ALTER TABLE waumini
                ADD CONSTRAINT waumini_group_id_fkey
                FOREIGN KEY (group_id)
                REFERENCES groups(id)
                ON DELETE SET NULL;

            END IF;

        END
        $$;
        """
        )

    # --------------------------------------------------------
    # MEMBERS
    # --------------------------------------------------------

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS waumini (
            id INTEGER
            GENERATED ALWAYS AS IDENTITY
            PRIMARY KEY,

            namba_ya_usajili TEXT
            NOT NULL UNIQUE,

            jina_kamili TEXT
            NOT NULL,

            makazi TEXT
            NOT NULL,

            jinsia TEXT
            NOT NULL,

            picha TEXT,

            namba_ya_sim TEXT,

            created_at TIMESTAMP
            NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # --------------------------------------------------------
    # MEMBER GROUPS
    # --------------------------------------------------------
    #
    # Kept temporarily for compatibility with the existing
    # database. The new system uses waumini.group_id.
    #
    # --------------------------------------------------------

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS member_groups (
            id INTEGER
            GENERATED ALWAYS AS IDENTITY
            PRIMARY KEY,

            member_id INTEGER
            NOT NULL,

            group_id INTEGER
            NOT NULL,

            joined_at TIMESTAMP
            NOT NULL DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT
                member_groups_member_id_fkey

            FOREIGN KEY (
                member_id
            )

            REFERENCES waumini(id)

            ON DELETE CASCADE,

            CONSTRAINT
                member_groups_group_id_fkey

            FOREIGN KEY (
                group_id
            )

            REFERENCES groups(id)

            ON DELETE CASCADE,

            CONSTRAINT
                member_groups_unique

            UNIQUE (
                member_id,
                group_id
            )
        )
        """
    )

    # --------------------------------------------------------
    # PERMISSIONS SEED
    # --------------------------------------------------------

    permission_names = [

        "dashboard.view",

        "members.view",
        "members.create",
        "members.edit",
        "members.delete",

        "admins.view",
        "admins.create",
        "admins.manage",

        "audit.view",

        "settings.view",
        "settings.manage",

        "subzones.view",
        "subzones.create",
        "subzones.edit",
        "subzones.delete",

        "announcements.view",
        "announcements.create",
        "announcements.edit",
        "announcements.delete",

        "groups.view",
        "groups.create",
        "groups.edit",
        "groups.delete"
    ]

    for permission_name in permission_names:

        db.execute(
            """
            INSERT INTO permissions (
                name
            )
            VALUES (%s)
            ON CONFLICT (name)
            DO NOTHING
            """,
            (permission_name,)
        )

    # --------------------------------------------------------
    # ROLES SEED
    # --------------------------------------------------------

    role_names = [
        "superadmin",
        "admin",
        "secretary",
        "treasurer"
    ]

    for role_name in role_names:

        db.execute(
            """
            INSERT INTO roles (
                name
            )
            VALUES (%s)
            ON CONFLICT (name)
            DO NOTHING
            """,
            (role_name,)
        )

    # --------------------------------------------------------
    # SUPERADMIN
    # --------------------------------------------------------

    db.execute(
        """
        INSERT INTO role_permissions (
            role_id,
            permission_id
        )

        SELECT
            r.id,
            p.id

        FROM roles r

        CROSS JOIN permissions p

        WHERE r.name = 'superadmin'

        ON CONFLICT (
            role_id,
            permission_id
        )
        DO NOTHING
        """
    )

    # --------------------------------------------------------
    # ADMIN PERMISSIONS
    # --------------------------------------------------------

    admin_permissions = [

        "dashboard.view",

        "members.view",
        "members.create",
        "members.edit",
        "members.delete",

        "admins.view",
        "admins.create",
        "admins.manage",

        "audit.view",

        "settings.view",
        "settings.manage",

        "subzones.view",
        "subzones.create",
        "subzones.edit",
        "subzones.delete",

        "announcements.view",
        "announcements.create",
        "announcements.edit",
        "announcements.delete",

        "groups.view",
        "groups.create",
        "groups.edit",
        "groups.delete"
    ]

    for permission_name in admin_permissions:

        db.execute(
            """
            INSERT INTO role_permissions (
                role_id,
                permission_id
            )

            SELECT
                r.id,
                p.id

            FROM roles r

            CROSS JOIN permissions p

            WHERE r.name = 'admin'
            AND p.name = %s

            ON CONFLICT (
                role_id,
                permission_id
            )
            DO NOTHING
            """,
            (permission_name,)
        )

    # --------------------------------------------------------
    # SECRETARY PERMISSIONS
    # --------------------------------------------------------

    secretary_permissions = [

        "dashboard.view",

        "members.view",
        "members.create",
        "members.edit",

        "subzones.view",

        "announcements.view",
        "announcements.create",
        "announcements.edit",

        "groups.view"
    ]

    for permission_name in secretary_permissions:

        db.execute(
            """
            INSERT INTO role_permissions (
                role_id,
                permission_id
            )

            SELECT
                r.id,
                p.id

            FROM roles r

            CROSS JOIN permissions p

            WHERE r.name = 'secretary'
            AND p.name = %s

            ON CONFLICT (
                role_id,
                permission_id
            )
            DO NOTHING
            """,
            (permission_name,)
        )

    # --------------------------------------------------------
    # TREASURER PERMISSIONS
    # --------------------------------------------------------

    treasurer_permissions = [

        "dashboard.view",

        "members.view",

        "subzones.view",
        "groups.view"
    ]

    for permission_name in treasurer_permissions:

        db.execute(
            """
            INSERT INTO role_permissions (
                role_id,
                permission_id
            )

            SELECT
                r.id,
                p.id

            FROM roles r

            CROSS JOIN permissions p

            WHERE r.name = 'treasurer'
            AND p.name = %s

            ON CONFLICT (
                role_id,
                permission_id
            )
            DO NOTHING
            """,
            (permission_name,)
        )

    # --------------------------------------------------------
    # INITIAL ADMIN
    # --------------------------------------------------------

    initial_password = os.getenv(
        "INITIAL_ADMIN_PASSWORD",
        "ChangeMeImmediately123!"
    )

    admin_role = db.execute(
        """
        SELECT
            id
        FROM roles
        WHERE name = 'superadmin'
        """
    ).fetchone()

    if admin_role:

        existing_admin = db.execute(
            """
            SELECT
                id
            FROM admins
            WHERE username = 'admin'
            """
        ).fetchone()

        if not existing_admin:

            db.execute(
                """
                INSERT INTO admins (
                    username,
                    password_hash,
                    full_name,
                    email,
                    role_id,
                    is_active
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    TRUE
                )
                """,
                (
                    "admin",
                    generate_password_hash(
                        initial_password
                    ),
                    "System Administrator",
                    "admin@example.com",
                    admin_role["id"]
                )
            )

    db.commit()
 # ============================================================
# AUTHENTICATION & PERMISSIONS
# ============================================================

def get_current_admin():

    admin_id = session.get("admin_id")

    if not admin_id:
        return None

    db = get_db()

    admin = db.execute(
        """
        SELECT
            admins.id,
            admins.username,
            admins.full_name,
            admins.is_active,
            admins.role_id,
            roles.name AS role_name
        FROM admins
        JOIN roles
            ON admins.role_id = roles.id
        WHERE admins.id = %s
        """,
        (admin_id,)
    ).fetchone()

    if not admin:

        session.clear()

        return None

    if not admin["is_active"]:

        session.clear()

        return None

    permissions = db.execute(
        """
        SELECT
            permissions.name
        FROM permissions
        JOIN role_permissions
            ON permissions.id = role_permissions.permission_id
        WHERE role_permissions.role_id = %s
        """,
        (admin["role_id"],)
    ).fetchall()

    admin = dict(admin)

    admin["permissions"] = {
        row["name"]
        for row in permissions
    }

    return admin


def login_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        admin = get_current_admin()

        if not admin:

            flash(
                "Tafadhali ingia kwanza.",
                "error"
            )

            return redirect(
                url_for("login")
            )

        return view(*args, **kwargs)

    return wrapped_view


def permission_required(permission):

    def decorator(view):

        @wraps(view)
        def wrapped_view(*args, **kwargs):

            admin = get_current_admin()

            if not admin:
                flash(
                    "Tafadhali ingia kwanza.",
                    "error"
                )

                return redirect(
                    url_for("login")
                )

            permissions = admin.get(
                "permissions",
                set()
            )

            if (
                permission not in permissions
                and admin.get("role_name") != "superadmin"
            ):

                return render_template(
                    "403.html"
                ), 403

            return view(*args, **kwargs)

        return wrapped_view

    return decorator


# ============================================================
# AUDIT LOGGING
# ============================================================

def log_action(
    action,
    description=""
):

    admin = get_current_admin()

    if not admin:
        return

    db = get_db()

    ip_address = (
        request.headers.get(
            "X-Forwarded-For",
            request.remote_addr
        )
    )

    if ip_address and "," in ip_address:
        ip_address = (
            ip_address
            .split(",")[0]
            .strip()
        )

    db.execute(
        """
        INSERT INTO audit_logs (
            admin_id,
            action,
            description,
            ip_address
        )
        VALUES (
            %s,
            %s,
            %s,
            %s
        )
        """,
        (
            admin["id"],
            action,
            description,
            ip_address
        )
    )

# ============================================================
# GLOBAL TEMPLATE VARIABLES
# ============================================================

@app.context_processor
def inject_global_variables():

    admin = get_current_admin()

    if admin:

        permissions = admin.get(
            "permissions",
            set()
        )

        is_superadmin = (
            admin.get("role_name")
            == "superadmin"
        )

    else:

        permissions = set()

        is_superadmin = False

    def has_permission(permission):

        return (
            is_superadmin
            or permission in permissions
        )

    return {

        "has_permission":
            has_permission,

        "current_admin": admin,

        "church_settings":
            get_church_settings(),

        "is_superadmin":
            is_superadmin,

        # Members
        "can_view_members":
            is_superadmin
            or "members.view"
            in permissions,

        "can_create_members":
            is_superadmin
            or "members.create"
            in permissions,

        "can_edit_members":
            is_superadmin
            or "members.edit"
            in permissions,

        "can_delete_members":
            is_superadmin
            or "members.delete"
            in permissions,

        # Admins
        "can_view_admins":
            is_superadmin
            or "admins.view"
            in permissions,

        "can_create_admins":
            is_superadmin
            or "admins.create"
            in permissions,

        "can_manage_admins":
            is_superadmin
            or "admins.manage"
            in permissions,

        # Audit
        "can_view_audit":
            is_superadmin
            or "audit.view"
            in permissions,

        # Settings
        "can_view_settings":
            is_superadmin
            or "settings.view"
            in permissions,

        "can_manage_settings":
            is_superadmin
            or "settings.manage"
            in permissions,

        # Subzones
        "can_view_subzones":
            is_superadmin
            or "subzones.view"
            in permissions,

        "can_create_subzones":
            is_superadmin
            or "subzones.create"
            in permissions,

        "can_edit_subzones":
            is_superadmin
            or "subzones.edit"
            in permissions,

        "can_delete_subzones":
            is_superadmin
            or "subzones.delete"
            in permissions,

        # Announcements
        "can_view_announcements":
            is_superadmin
            or "announcements.view"
            in permissions,

        "can_create_announcements":
            is_superadmin
            or "announcements.create"
            in permissions,

        "can_edit_announcements":
            is_superadmin
            or "announcements.edit"
            in permissions,

        "can_delete_announcements":
            is_superadmin
            or "announcements.delete"
            in permissions,

       # Groups 
        "can_view_groups":
            is_superadmin
             or "groups.view"
            in permissions,

        "can_create_groups":
            is_superadmin
            or "groups.create"
            in permissions,

        "can_edit_groups":
            is_superadmin
            or "groups.edit"
            in permissions,

        "can_delete_groups":
            is_superadmin
             or "groups.delete"
             in permissions,

        # Finance
        "can_view_finance":
            is_superadmin
            or "finance.view"
            in permissions,

        "can_create_finance":
            is_superadmin
            or "finance.create"
            in permissions,

        "can_edit_finance":
            is_superadmin
            or "finance.edit"
            in permissions,

        "can_delete_finance":
            is_superadmin
            or "finance.delete"
            in permissions,

        "can_view_finance_reports":
            is_superadmin
            or "finance.reports"
            in permissions
    }

# ============================================================
# PUBLIC HOMEPAGE
# ============================================================

@app.route("/")
def home():

    db = get_db()

    announcements = db.execute(
        """
        SELECT
            id,
            title,
            content,
            image,
            created_at
        FROM announcements
        WHERE published = TRUE
        ORDER BY created_at DESC
        """
    ).fetchall()

    return render_template(
        "home.html",
        announcements=announcements
    )


# ============================================================
# PUBLIC REGISTRATION
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    db = get_db()

    subzones = get_active_subzones()

    if request.method == "POST":

        jina_kamili = request.form.get(
            "jina_kamili",
            ""
        ).strip()

        makazi = request.form.get(
            "makazi",
            ""
        ).strip()

        jinsia = request.form.get(
            "jinsia",
            ""
        ).strip()

        namba_ya_sim = request.form.get(
            "namba_ya_sim",
            ""
        ).strip()

        subzone_id = request.form.get(
            "subzone_id",
            ""
        ).strip()
        photo = request.files.get("picha")

        if not jina_kamili:

            flash(
                "Jina kamili linahitajika.",
                "error"
            )

            return render_template(
                "register.html",
                subzones=subzones
            )

        if not makazi:

            flash(
                "Makazi yanahitajika.",
                "error"
            )

            return render_template(
                "register.html",
                subzones=subzones
            )

        if not jinsia:

            flash(
                "Jinsia inahitajika.",
                "error"
            )

            return render_template(
                "register.html",
                subzones=subzones
            )

        if not namba_ya_sim:

            flash(
                "Namba ya simu inahitajika.",
                "error"
            )

            return render_template(
                "register.html",
                subzones=subzones
            )

        phone_pattern = (
            r"^(0\d{9}|\+255\d{9})$"
        )

        if not re.match(
            phone_pattern,
            namba_ya_sim
        ):

            flash(
                "Namba ya simu si sahihi.",
                "error"
            )

            return render_template(
                "register.html",
                subzones=subzones
            )

        selected_subzone = None

        if subzone_id:

            try:

                subzone_id_int = int(
                    subzone_id
                )

            except ValueError:

                flash(
                    "Subzone si sahihi.",
                    "error"
                )

                return render_template(
                    "register.html",
                    subzones=subzones
                )

            selected_subzone = db.execute(
                """
                SELECT
                    id,
                    name
                FROM subzones
                WHERE id = %s
                AND active = 1
                """,
                (subzone_id_int,)
            ).fetchone()

            if not selected_subzone:

                flash(
                    "Subzone iliyochaguliwa haipo.",
                    "error"
                )

                return render_template(
                    "register.html",
                    subzones=subzones
                )

        registration_number = (
            generate_registration_number()
        )

        uploaded_filename = None

        image = request.files.get(
            "picha"
        )

        if image and image.filename:

            if not allowed_file(
                image.filename
            ):

                flash(
                    "Aina ya picha hairuhusiwi.",
                    "error"
                )

                return render_template(
                    "register.html",
                    subzones=subzones
                )

            uploaded_filename = (
                save_uploaded_image(
                    image
                )
            )

        db.execute(
            """
            INSERT INTO waumini (
                namba_ya_usajili,
                jina_kamili,
                makazi,
                jinsia,
                picha,
                namba_ya_sim,
                subzone_id
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                registration_number,
                jina_kamili,
                makazi,
                jinsia,
                uploaded_filename,
                namba_ya_sim,
                (
                    selected_subzone["id"]
                    if selected_subzone
                    else None
                )
            )
        )

        flash(
            "Usajili umefanikiwa.",
            "success"
        )

        return render_template(
            "success.html",
            registration_number=(
                registration_number
            ),
            jina_kamili=jina_kamili
        )

    return render_template(
        "register.html",
        subzones=subzones
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        db = get_db()

        admin = db.execute(
            """
            SELECT
                admins.id,
                admins.username,
                admins.password_hash,
                admins.full_name,
                admins.is_active,
                admins.role_id,
                roles.name AS role_name
            FROM admins
            JOIN roles
                ON admins.role_id = roles.id
            WHERE admins.username = %s
            """,
            (username,)
        ).fetchone()

        if (
            not admin
            or not admin["is_active"]
            or not check_password_hash(
                admin["password_hash"],
                password
            )
        ):

            flash(
                "Username au password si sahihi.",
                "error"
            )

            return render_template(
                "login.html"
            )

        session.clear()

        session["admin_id"] = admin["id"]

        flash(
            "Umeingia kwenye mfumo.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html"
    )




# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
@login_required
def logout():

    admin = get_current_admin()

    if admin:

        log_action(
            "LOGOUT",
            "Admin logged out"
        )

    session.clear()

    flash(
        "Umetoka kwenye mfumo.",
        "success"
    )

    return redirect(
        url_for("home")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
@permission_required("dashboard.view")
def dashboard():

    db = get_db()

    jumla = db.execute(
        """
        SELECT
            COUNT(*) AS count
        FROM waumini
        """
    ).fetchone()["count"]

    wanaume = db.execute(
        """
        SELECT
            COUNT(*) AS count
        FROM waumini
        WHERE LOWER(TRIM(jinsia))
        IN (
            'mwanaume',
            'mume',
            'male'
        )
        """
    ).fetchone()["count"]

    wanawake = db.execute(
        """
        SELECT
            COUNT(*) AS count
        FROM waumini
        WHERE LOWER(TRIM(jinsia))
        IN (
            'mwanamke',
            'mke',
            'female'
        )
        """
    ).fetchone()["count"]

    mwaka = datetime.now().year

    waliosajiliwa_mwaka_huu = db.execute(
        """
        SELECT
            COUNT(*) AS count
        FROM waumini
        WHERE namba_ya_usajili LIKE %s
        """,
        (
            f"WM-{mwaka}-%",
        )
    ).fetchone()["count"]

    makazi = db.execute(
        """
        SELECT
            makazi,
            COUNT(*) AS idadi
        FROM waumini
        WHERE makazi IS NOT NULL
        AND TRIM(makazi) <> ''
        GROUP BY makazi
        ORDER BY idadi DESC
        """
    ).fetchall()

    return render_template(
        "dashboard.html",
        jumla=jumla,
        wanaume=wanaume,
        wanawake=wanawake,
        mwaka=mwaka,
        waliosajiliwa_mwaka_huu=(
            waliosajiliwa_mwaka_huu
        ),
        makazi=makazi
    )


# ============================================================
# MEMBERS
# ============================================================

@app.route("/finance")
@login_required
@permission_required("finance.view")
def finance_dashboard():

    db = get_db()

    total_income = db.execute(
        """
        SELECT COALESCE(
            SUM(amount),
            0
        ) AS total
        FROM finance_transactions
        WHERE transaction_type = 'income'
        """
    ).fetchone()["total"]

    total_expenses = db.execute(
        """
        SELECT COALESCE(
            SUM(amount),
            0
        ) AS total
        FROM finance_transactions
        WHERE transaction_type = 'expense'
        """
    ).fetchone()["total"]

    balance = total_income - total_expenses

    recent_transactions = db.execute(
        """
        SELECT
            f.id,
            f.transaction_type,
            f.category,
            f.amount,
            f.description,
            f.transaction_date,
            f.member_id,
            w.jina_kamili AS member_name
        FROM finance_transactions f
        LEFT JOIN waumini w
            ON f.member_id = w.id
        ORDER BY
            f.transaction_date DESC,
            f.id DESC
        LIMIT 20
        """
    ).fetchall()

    return render_template(
        "finance_dashboard.html",
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        recent_transactions=recent_transactions
    )

@app.route("/finance/search-members")
@login_required
@permission_required("finance.create")
def search_finance_members():

    query = request.args.get(
        "q",
        ""
    ).strip()

    if len(query) < 2:
        return jsonify([])

    db = get_db()

    members = db.execute(
        """
        SELECT
            id,
            jina_kamili,
            namba_ya_usajili
        FROM waumini
        WHERE
            jina_kamili ILIKE %s
            OR namba_ya_usajili ILIKE %s
        ORDER BY jina_kamili ASC
        LIMIT 10
        """,
        (
            f"%{query}%",
            f"%{query}%"
        )
    ).fetchall()

    return jsonify(
        [
            {
                "id": member["id"],
                "jina_kamili": member["jina_kamili"],
                "namba_ya_usajili": member["namba_ya_usajili"]
            }
            for member in members
        ]
    )



@app.route("/finance/income", methods=["GET", "POST"])
@login_required
@permission_required("finance.create")
def add_income():

    db = get_db()

    if request.method == "POST":

        category = request.form.get("category", "").strip()
        member_id = request.form.get("member_id", "").strip()
        amount = request.form.get("amount", "").strip()
        transaction_date = request.form.get("transaction_date", "").strip()
        description = request.form.get("description", "").strip()

        # Basic validation
        if not category:
            return "Aina ya mapato inahitajika.", 400

        if not amount:
            return "Kiasi kinahitajika.", 400

        if not transaction_date:
            return "Tarehe inahitajika.", 400

        try:
            amount = float(amount)
        except ValueError:
            return "Kiasi si sahihi.", 400

        if amount <= 0:
            return "Kiasi lazima kiwe zaidi ya sifuri.", 400

        # Convert empty member ID to NULL
        if member_id == "":
            member_id = None
        else:
            try:
                member_id = int(member_id)
            except ValueError:
                return "Muumini aliyechaguliwa si sahihi.", 400

            # Make sure the member actually exists
            member_exists = db.execute(
                """
                SELECT id
                FROM waumini
                WHERE id = %s
                """,
                (member_id,)
            ).fetchone()

            if not member_exists:
                return "Muumini huyo hakupatikana.", 400

        # Save transaction
        db.execute(
            """
            INSERT INTO finance_transactions (
                member_id,
                transaction_type,
                category,
                amount,
                description,
                transaction_date,
                recorded_by
            )
            VALUES (
                %s,
                'income',
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                member_id,
                category,
                amount,
                description or None,
                transaction_date,
                session["admin_id"]
            )
        )

        log_action(
            "CREATE_FINANCE",
            f"Income recorded: {category}, TZS {amount:,.2f}"
        )

        return redirect(
            url_for("finance_dashboard")
        )

    # Load members for the dropdown
    members = db.execute(
        """
        SELECT
            id,
            namba_ya_usajili,
            jina_kamili
        FROM waumini
        ORDER BY jina_kamili ASC
        """
    ).fetchall()

    return render_template(
        "add_income.html",
        members=members
    )

@app.route("/members")
@login_required
@permission_required("members.view")
def members():

    db = get_db()

    search = request.args.get(
        "search",
        ""
    ).strip()

    jinsia_filter = request.args.get(
        "jinsia",
        ""
    ).strip()

    subzone_filter = request.args.get(
        "subzone",
        ""
    ).strip()

    query = """
        SELECT
            w.id,
            w.namba_ya_usajili,
            w.jina_kamili,
            w.makazi,
            w.jinsia,
            w.picha,
            w.namba_ya_sim,
            w.created_at,
            w.subzone_id,
            s.name AS subzone_name
        FROM waumini w
        LEFT JOIN subzones s
            ON s.id = w.subzone_id
        WHERE 1 = 1
    """

    params = []

    if search:

        query += """
            AND (
                LOWER(w.jina_kamili)
                LIKE LOWER(%s)

                OR LOWER(w.namba_ya_usajili)
                LIKE LOWER(%s)

                OR LOWER(w.makazi)
                LIKE LOWER(%s)

                OR LOWER(
                    COALESCE(
                        w.namba_ya_sim,
                        ''
                    )
                )
                LIKE LOWER(%s)
            )
        """

        search_value = f"%{search}%"

        params.extend(
            [
                search_value,
                search_value,
                search_value,
                search_value
            ]
        )

    if jinsia_filter:

        query += """
            AND LOWER(TRIM(w.jinsia))
            = LOWER(%s)
        """

        params.append(
            jinsia_filter
        )

    if subzone_filter:

        try:

            subzone_filter_id = int(
                subzone_filter
            )

            query += """
                AND w.subzone_id = %s
            """

            params.append(
                subzone_filter_id
            )

        except ValueError:
            pass

    query += """
        ORDER BY w.id DESC
    """

    member_list = db.execute(
        query,
        params
    ).fetchall()

    subzones = get_active_subzones()

    return render_template(
        "members.html",
        members=member_list,
        subzones=subzones,
        search=search,
        jinsia_filter=jinsia_filter,
        subzone_filter=subzone_filter
    )

@app.route("/finance/expenses", methods=["GET", "POST"])
@login_required
@permission_required("finance.create")
def add_expense():

    db = get_db()

    if request.method == "POST":

        category = request.form.get(
            "category",
            ""
        ).strip()

        amount = request.form.get(
            "amount",
            ""
        ).strip()

        transaction_date = request.form.get(
            "transaction_date",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        # Basic validation
        if not category:
            return "Aina ya matumizi inahitajika.", 400

        if not amount:
            return "Kiasi kinahitajika.", 400

        if not transaction_date:
            return "Tarehe inahitajika.", 400

        try:
            amount = float(amount)

        except ValueError:
            return "Kiasi si sahihi.", 400

        if amount <= 0:
            return "Kiasi lazima kiwe zaidi ya sifuri.", 400

        db.execute(
            """
            INSERT INTO finance_transactions (
                member_id,
                transaction_type,
                category,
                amount,
                description,
                transaction_date,
                recorded_by
            )
            VALUES (
                NULL,
                'expense',
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                category,
                amount,
                description or None,
                transaction_date,
                session["admin_id"]
            )
        )

        log_action(
            "CREATE_FINANCE",
            f"Expense recorded: {category}, TZS {amount:,.2f}"
        )

        return redirect(
            url_for("finance_dashboard")
        )

    return render_template(
        "add_expense.html"
    )

@app.route("/finance/reports")
@login_required
@permission_required("finance.reports")
def finance_reports():

    db = get_db()

    start_date = request.args.get(
        "start_date",
        ""
    ).strip()

    end_date = request.args.get(
        "end_date",
        ""
    ).strip()

    # Base conditions
    conditions = []
    params = []

    if start_date:
        conditions.append(
            "f.transaction_date >= %s"
        )
        params.append(start_date)

    if end_date:
        conditions.append(
            "f.transaction_date <= %s"
        )
        params.append(end_date)

    where_clause = ""

    if conditions:
        where_clause = (
            "WHERE "
            + " AND ".join(conditions)
        )

    # Summary
    summary = db.execute(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN f.transaction_type = 'income'
                        THEN f.amount
                        ELSE 0
                    END
                ),
                0
            ) AS total_income,

            COALESCE(
                SUM(
                    CASE
                        WHEN f.transaction_type = 'expense'
                        THEN f.amount
                        ELSE 0
                    END
                ),
                0
            ) AS total_expenses

        FROM finance_transactions f

        {where_clause}
        """,
        tuple(params)
    ).fetchone()

    total_income = summary["total_income"]
    total_expenses = summary["total_expenses"]

    balance = (
        total_income
        - total_expenses
    )

    # Income by category
        # Income by category

    category_conditions = list(conditions)

    category_conditions.append(
        "f.transaction_type = 'income'"
    )

    income_where = (
        "WHERE "
        + " AND ".join(category_conditions)
    )

    income_categories = db.execute(
        f"""
        SELECT
            category,
            SUM(amount) AS total

        FROM finance_transactions f

        {income_where}

        GROUP BY category

        ORDER BY total DESC
        """,
        tuple(params)
    ).fetchall()


    # Expenses by category

    category_conditions = list(conditions)

    category_conditions.append(
        "f.transaction_type = 'expense'"
    )

    expense_where = (
        "WHERE "
        + " AND ".join(category_conditions)
    )

    expense_categories = db.execute(
        f"""
        SELECT
            category,
            SUM(amount) AS total

        FROM finance_transactions f

        {expense_where}

        GROUP BY category

        ORDER BY total DESC
        """,
        tuple(params)
    ).fetchall()
    # Transactions
    transactions = db.execute(
        f"""
        SELECT
            f.id,
            f.transaction_type,
            f.category,
            f.amount,
            f.description,
            f.transaction_date,
            w.jina_kamili AS member_name

        FROM finance_transactions f

        LEFT JOIN waumini w
            ON f.member_id = w.id

        {where_clause}

        ORDER BY
            f.transaction_date DESC,
            f.id DESC
        """,
        tuple(params)
    ).fetchall()

    return render_template(
        "finance_reports.html",
        start_date=start_date,
        end_date=end_date,
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        income_categories=income_categories,
        expense_categories=expense_categories,
        transactions=transactions
    )

@app.route("/finance/export")
@login_required
@permission_required("finance.reports")
def export_finance_excel():

    db = get_db()

    start_date = request.args.get(
        "start_date",
        ""
    ).strip()

    end_date = request.args.get(
        "end_date",
        ""
    ).strip()

    conditions = []
    params = []

    if start_date:

        conditions.append(
            "f.transaction_date >= %s"
        )

        params.append(
            start_date
        )

    if end_date:

        conditions.append(
            "f.transaction_date <= %s"
        )

        params.append(
            end_date
        )

    where_clause = ""

    if conditions:

        where_clause = (
            "WHERE "
            + " AND ".join(conditions)
        )

    transactions = db.execute(
        f"""
        SELECT
            f.id,
            f.transaction_type,
            f.category,
            f.amount,
            f.description,
            f.transaction_date,
            w.jina_kamili AS member_name,
            w.namba_ya_usajili AS registration_number,
            a.username AS recorded_by

        FROM finance_transactions f

        LEFT JOIN waumini w
            ON f.member_id = w.id

        LEFT JOIN admins a
            ON f.recorded_by = a.id

        {where_clause}

        ORDER BY
            f.transaction_date ASC,
            f.id ASC
        """,
        tuple(params)
    ).fetchall()

    workbook = Workbook()

    worksheet = workbook.active

    worksheet.title = "Finance Transactions"

    headers = [
        "ID",
        "Tarehe",
        "Aina",
        "Category",
        "Mwanachama",
        "Namba ya Usajili",
        "Maelezo",
        "Kiasi (TZS)",
        "Aliyeingiza"
    ]

    worksheet.append(headers)

    for cell in worksheet[1]:

        cell.font = Font(
            bold=True
        )

        cell.alignment = Alignment(
            horizontal="center"
        )

    for transaction in transactions:

        transaction_type = (
            "Mapato"
            if transaction["transaction_type"]
            == "income"
            else "Matumizi"
        )

        worksheet.append(
            [
                transaction["id"],
                transaction["transaction_date"],
                transaction_type,
                transaction["category"],
                transaction["member_name"] or "",
                transaction["registration_number"] or "",
                transaction["description"] or "",
                float(transaction["amount"]),
                transaction["recorded_by"] or ""
            ]
        )

    for row in worksheet.iter_rows(
        min_row=2,
        min_col=8,
        max_col=8
    ):

        row[0].number_format = (
            '#,##0.00'
        )

    worksheet.freeze_panes = "A2"

    worksheet.auto_filter.ref = (
        worksheet.dimensions
    )

    column_widths = {
        "A": 10,
        "B": 15,
        "C": 15,
        "D": 25,
        "E": 30,
        "F": 20,
        "G": 40,
        "H": 18,
        "I": 20
    }

    for column, width in column_widths.items():

        worksheet.column_dimensions[
            column
        ].width = width

    output = BytesIO()

    workbook.save(output)

    output.seek(0)

    filename = "finance_report"

    if start_date and end_date:

        filename = (
            f"finance_report_"
            f"{start_date}_"
            f"to_"
            f"{end_date}"
        )

    elif start_date:

        filename = (
            f"finance_report_from_"
            f"{start_date}"
        )

    elif end_date:

        filename = (
            f"finance_report_until_"
            f"{end_date}"
        )

    log_action(
        "EXPORT_FINANCE",
        (
            "Exported finance report"
            f" ({start_date or 'beginning'}"
            f" to "
            f"{end_date or 'present'})"
        )
    )

    return send_file(
        output,
        as_attachment=True,
        download_name=f"{filename}.xlsx",
        mimetype=(
            "application/"
            "vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )


@app.route(
    "/finance/import",
    methods=["GET", "POST"]
)
@login_required
@permission_required("finance.create")
def import_finance_excel():

    db = get_db()

    if request.method == "POST":

        excel_file = request.files.get(
            "excel_file"
        )

        if not excel_file:
            flash(
                "Tafadhali chagua Excel file.",
                "error"
            )
            return redirect(
                url_for("import_finance_excel")
            )

        if not excel_file.filename:
            flash(
                "Tafadhali chagua Excel file.",
                "error"
            )
            return redirect(
                url_for("import_finance_excel")
            )

        if not excel_file.filename.lower().endswith(
            ".xlsx"
        ):
            flash(
                "Tafadhali tumia Excel file ya .xlsx.",
                "error"
            )
            return redirect(
                url_for("import_finance_excel")
            )

        try:

            workbook = load_workbook(
                excel_file,
                read_only=True,
                data_only=True
            )

        except Exception:

            flash(
                "Excel file haiwezi kusomwa.",
                "error"
            )

            return redirect(
                url_for("import_finance_excel")
            )

        worksheet = workbook.active

        rows = list(
            worksheet.iter_rows(
                values_only=True
            )
        )

        workbook.close()

        if not rows:

            flash(
                "Excel file haina data.",
                "error"
            )

            return redirect(
                url_for("import_finance_excel")
            )

        expected_headers = [
            "Tarehe",
            "Aina",
            "Category",
            "Namba ya Usajili",
            "Maelezo",
            "Kiasi (TZS)"
        ]

        headers = [
            str(value).strip()
            if value is not None
            else ""
            for value in rows[0]
        ]

        if headers != expected_headers:

            flash(
                (
                    "Muundo wa Excel si sahihi. "
                    "Tumia template ya Finance Export."
                ),
                "error"
            )

            return redirect(
                url_for("import_finance_excel")
            )

        data_rows = rows[1:]

        if not data_rows:

            flash(
                "Excel file haina transactions.",
                "error"
            )

            return redirect(
                url_for("import_finance_excel")
            )

        errors = []
        valid_transactions = []

        for row_number, row in enumerate(
            data_rows,
            start=2
        ):

            if not any(
                value is not None
                and str(value).strip() != ""
                for value in row
            ):
                continue

            row = list(row)

            while len(row) < 6:
                row.append(None)

            transaction_date = row[0]
            transaction_type = row[1]
            category = row[2]
            registration_number = row[3]
            description = row[4]
            amount = row[5]

            row_errors = []

            if not transaction_date:

                row_errors.append(
                    "Tarehe haipo"
                )

            if transaction_type:

                transaction_type = str(
                    transaction_type
                ).strip().lower()

                if transaction_type in (
                    "mapato",
                    "income"
                ):

                    transaction_type = "income"

                elif transaction_type in (
                    "matumizi",
                    "expense",
                    "expenses"
                ):

                    transaction_type = "expense"

                else:

                    row_errors.append(
                        "Aina lazima iwe Mapato au Matumizi"
                    )

            else:

                row_errors.append(
                    "Aina haipo"
                )

            if not category:

                row_errors.append(
                    "Category haipo"
                )

            else:

                category = str(
                    category
                ).strip()

            if amount is None:

                row_errors.append(
                    "Kiasi hakipo"
                )

            else:

                try:

                    amount = float(
                        amount
                    )

                    if amount <= 0:

                        row_errors.append(
                            "Kiasi lazima kiwe zaidi ya sifuri"
                        )

                except (
                    TypeError,
                    ValueError
                ):

                    row_errors.append(
                        "Kiasi si sahihi"
                    )

            member_id = None

            if registration_number:

                registration_number = str(
                    registration_number
                ).strip()

                member = db.execute(
                    """
                    SELECT
                        id
                    FROM waumini
                    WHERE namba_ya_usajili = %s
                    """,
                    (
                        registration_number,
                    )
                ).fetchone()

                if not member:

                    row_errors.append(
                        (
                            "Namba ya usajili "
                            "haikupatikana"
                        )
                    )

                else:

                    member_id = member["id"]

            else:

                registration_number = None

            if transaction_date:

                if hasattr(
                    transaction_date,
                    "date"
                ):

                    transaction_date = (
                        transaction_date.date()
                    )

                else:

                    try:

                        transaction_date = (
                            datetime.strptime(
                                str(
                                    transaction_date
                                ).strip(),
                                "%Y-%m-%d"
                            ).date()
                        )

                    except ValueError:

                        row_errors.append(
                            (
                                "Tarehe lazima iwe "
                                "YYYY-MM-DD"
                            )
                        )

            if description is not None:

                description = str(
                    description
                ).strip()

            else:

                description = None

            if row_errors:

                errors.append(
                    {
                        "row": row_number,
                        "errors": row_errors
                    }
                )

            else:

                valid_transactions.append(
                    {
                        "transaction_date":
                            transaction_date,
                        "transaction_type":
                            transaction_type,
                        "category":
                            category,
                        "member_id":
                            member_id,
                        "description":
                            description,
                        "amount":
                            amount
                    }
                )

        if errors:

            return render_template(
                "finance_import.html",
                errors=errors,
                valid_count=len(
                    valid_transactions
                ),
                imported=False
            )

        try:

            for transaction in valid_transactions:

                db.execute(
                    """
                    INSERT INTO finance_transactions (
                        member_id,
                        transaction_type,
                        category,
                        amount,
                        description,
                        transaction_date,
                        recorded_by
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        transaction["member_id"],
                        transaction["transaction_type"],
                        transaction["category"],
                        transaction["amount"],
                        transaction["description"],
                        transaction["transaction_date"],
                        session["admin_id"]
                    )
                )

            log_action(
                "IMPORT_FINANCE",
                (
                    "Imported "
                    f"{len(valid_transactions)} "
                    "finance transactions from Excel"
                )
            )

            flash(
                (
                    f"Transactions "
                    f"{len(valid_transactions)} "
                    "zimeingizwa kikamilifu."
                ),
                "success"
            )

            return redirect(
                url_for("finance_transactions")
            )

        except Exception:

            db.rollback()

            flash(
                (
                    "Imeshindikana kuingiza "
                    "transactions. Hakuna data "
                    "iliyoingizwa."
                ),
                "error"
            )

            return redirect(
                url_for("import_finance_excel")
            )

    return render_template(
        "finance_import.html",
        errors=[],
        valid_count=0,
        imported=False
    )

@app.route("/finance/transactions")
@login_required
@permission_required("finance.view")
def finance_transactions():

    db = get_db()

    transactions = db.execute(
        """
        SELECT
            f.id,
            f.transaction_type,
            f.category,
            f.amount,
            f.description,
            f.transaction_date,
            f.member_id,
            w.jina_kamili AS member_name,
            a.username AS recorded_by
        FROM finance_transactions f

        LEFT JOIN waumini w
            ON f.member_id = w.id

        LEFT JOIN admins a
            ON f.recorded_by = a.id

        ORDER BY
            f.transaction_date DESC,
            f.id DESC
        """
    ).fetchall()

    return render_template(
        "finance_transactions.html",
        transactions=transactions
    )

@app.route(
    "/finance/transactions/<int:transaction_id>/edit",
    methods=["GET", "POST"]
)
@login_required
@permission_required("finance.edit")
def edit_finance_transaction(transaction_id):

    db = get_db()

    transaction = db.execute(
        """
        SELECT
            id,
            member_id,
            transaction_type,
            category,
            amount,
            description,
            transaction_date
        FROM finance_transactions
        WHERE id = %s
        """,
        (transaction_id,)
    ).fetchone()

    if not transaction:
        return "Muamala haukupatikana.", 404

    if request.method == "POST":

        category = request.form.get(
            "category",
            ""
        ).strip()

        member_id = request.form.get(
            "member_id",
            ""
        ).strip()

        amount = request.form.get(
            "amount",
            ""
        ).strip()

        transaction_date = request.form.get(
            "transaction_date",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        if not category:
            return "Category inahitajika.", 400

        if not amount:
            return "Kiasi kinahitajika.", 400

        if not transaction_date:
            return "Tarehe inahitajika.", 400

        try:
            amount = float(amount)
        except ValueError:
            return "Kiasi si sahihi.", 400

        if amount <= 0:
            return "Kiasi lazima kiwe zaidi ya sifuri.", 400

        if member_id == "":
            member_id = None

        else:
            try:
                member_id = int(member_id)

            except ValueError:
                return "Muumini aliyechaguliwa si sahihi.", 400

            member_exists = db.execute(
                """
                SELECT id
                FROM waumini
                WHERE id = %s
                """,
                (member_id,)
            ).fetchone()

            if not member_exists:
                return "Muumini huyo hakupatikana.", 400

        db.execute(
            """
            UPDATE finance_transactions
            SET
                category = %s,
                member_id = %s,
                amount = %s,
                description = %s,
                transaction_date = %s
            WHERE id = %s
            """,
            (
                category,
                member_id,
                amount,
                description or None,
                transaction_date,
                transaction_id
            )
        )

        log_action(
            "EDIT_FINANCE",
            f"Finance transaction edited: ID {transaction_id}"
        )

        return redirect(
            url_for("finance_transactions")
        )

    members = db.execute(
        """
        SELECT
            id,
            namba_ya_usajili,
            jina_kamili
        FROM waumini
        ORDER BY jina_kamili ASC
        """
    ).fetchall()

    return render_template(
        "edit_finance_transaction.html",
        transaction=transaction,
        members=members
    )

@app.route(
    "/finance/transactions/<int:transaction_id>/delete",
    methods=["GET", "POST"]
)
@login_required
@permission_required("finance.delete")
def delete_finance_transaction(transaction_id):

    db = get_db()

    transaction = db.execute(
        """
        SELECT
            f.id,
            f.transaction_type,
            f.category,
            f.amount,
            f.description,
            f.transaction_date,
            w.jina_kamili AS member_name
        FROM finance_transactions f

        LEFT JOIN waumini w
            ON f.member_id = w.id

        WHERE f.id = %s
        """,
        (transaction_id,)
    ).fetchone()

    if not transaction:
        abort(404)

    if request.method == "POST":

        db.execute(
            """
            DELETE FROM finance_transactions
            WHERE id = %s
            """,
            (transaction_id,)
        )

        log_action(
            "DELETE_FINANCE",
            (
                "Deleted finance transaction ID "
                f"{transaction_id}: "
                f"{transaction['transaction_type']} - "
                f"{transaction['category']} - "
                f"TZS {transaction['amount']:,.2f}"
            )
        )

        flash(
            "Muamala umefutwa.",
            "success"
        )

        return redirect(
            url_for("finance_transactions")
        )

    return render_template(
        "delete_finance_transaction.html",
        transaction=transaction
    )


# ============================================================
# EDIT MEMBER
# ============================================================

@app.route(
    "/members/<int:member_id>/edit",
    methods=["GET", "POST"]
)
@login_required
@permission_required("members.edit")
def edit_member(member_id):

    db = get_db()

    member = db.execute(
        """
        SELECT
            id,
            namba_ya_usajili,
            jina_kamili,
            makazi,
            jinsia,
            picha,
            namba_ya_sim,
            subzone_id,
            created_at
        FROM waumini
        WHERE id = %s
        """,
        (member_id,)
    ).fetchone()

    if not member:
        abort(404)

    subzones = get_active_subzones()

    if request.method == "POST":

        jina_kamili = request.form.get(
            "jina_kamili",
            ""
        ).strip()

        makazi = request.form.get(
            "makazi",
            ""
        ).strip()

        jinsia = request.form.get(
            "jinsia",
            ""
        ).strip()

        namba_ya_sim = request.form.get(
            "namba_ya_sim",
            ""
        ).strip()

        subzone_id = request.form.get(
            "subzone_id",
            ""
        ).strip()

        photo = request.files.get("picha")

        if not jina_kamili:
            flash(
                "Jina kamili linahitajika.",
                "error"
            )
            return render_template(
                "edit.html",
                member=member,
                subzones=subzones
            )

        if not makazi:
            flash(
                "Makazi yanahitajika.",
                "error"
            )
            return render_template(
                "edit.html",
                member=member,
                subzones=subzones
            )

        if not jinsia:
            flash(
                "Jinsia inahitajika.",
                "error"
            )
            return render_template(
                "edit.html",
                member=member,
                subzones=subzones
            )

        if not namba_ya_sim:
            flash(
                "Namba ya simu inahitajika.",
                "error"
            )
            return render_template(
                "edit.html",
                member=member,
                subzones=subzones
            )

        phone_pattern = (
            r"^(0\d{9}|\+255\d{9})$"
        )

        if not re.match(
            phone_pattern,
            namba_ya_sim
        ):
            flash(
                "Namba ya simu si sahihi.",
                "error"
            )
            return render_template(
                "edit.html",
                member=member,
                subzones=subzones
            )

        selected_subzone_id = None

        if subzone_id:

            try:
                selected_subzone_id = int(
                    subzone_id
                )

            except ValueError:

                flash(
                    "Subzone si sahihi.",
                    "error"
                )

                return render_template(
                    "edit.html",
                    member=member,
                    subzones=subzones
                )

            selected_subzone = db.execute(
                """
                SELECT
                    id
                FROM subzones
                WHERE id = %s
                AND active = 1
                """,
                (
                    selected_subzone_id,
                )
            ).fetchone()

            if not selected_subzone:

                flash(
                    "Subzone iliyochaguliwa haipo.",
                    "error"
                )

                return render_template(
                    "edit.html",
                    member=member,
                    subzones=subzones
                )

        # Keep the current photo unless a new one is uploaded.
        new_photo = member["picha"]

        if photo and photo.filename:

            if not allowed_file(photo.filename):

                flash(
                    "Aina ya picha hairuhusiwi. Tumia JPG, JPEG, PNG au WEBP.",
                    "error"
                )

                return render_template(
                    "edit.html",
                    member=member,
                    subzones=subzones
                )

            try:

                new_photo = save_uploaded_image(
                    photo
                )

            except Exception:

                flash(
                    "Imeshindikana kupakia picha.",
                    "error"
                )

                return render_template(
                    "edit.html",
                    member=member,
                    subzones=subzones
                )

        db.execute(
            """
            UPDATE waumini
            SET
                jina_kamili = %s,
                makazi = %s,
                jinsia = %s,
                namba_ya_sim = %s,
                subzone_id = %s,
                picha = %s
            WHERE id = %s
            """,
            (
                jina_kamili,
                makazi,
                jinsia,
                namba_ya_sim,
                selected_subzone_id,
                new_photo,
                member_id
            )
        )

        # Delete the old photo only after
        # the database has been updated successfully.
        if (
            photo
            and photo.filename
            and member["picha"]
            and new_photo != member["picha"]
        ):
            delete_uploaded_file(
                member["picha"]
            )

        log_action(
            "EDIT_MEMBER",
            (
                "Edited member ID "
                f"{member_id}"
            )
        )

        flash(
            "Taarifa za muumini zimebadilishwa.",
            "success"
        )

        return redirect(
            url_for("members")
        )

    return render_template(
        "edit.html",
        member=member,
        subzones=subzones
    )


# ============================================================
# DELETE MEMBER
# ============================================================

@app.route(
    "/members/<int:member_id>/delete",
    methods=["GET", "POST"]
)
@login_required
@permission_required("members.delete")
def delete_member(member_id):

    db = get_db()

    member = db.execute(
        """
        SELECT
            id,
            namba_ya_usajili,
            jina_kamili,
            picha
        FROM waumini
        WHERE id = %s
        """,
        (member_id,)
    ).fetchone()

    if not member:
        abort(404)

    if request.method == "POST":

        db.execute(
            """
            DELETE FROM waumini
            WHERE id = %s
            """,
            (member_id,)
        )

        delete_uploaded_file(
            member["picha"]
        )

        log_action(
            "DELETE_MEMBER",
            (
                "Deleted member: "
                f"{member['jina_kamili']}"
            )
        )

        flash(
            "Muumini amefutwa.",
            "success"
        )

        return redirect(
            url_for("members")
        )

    return render_template(
        "delete.html",
        member=member
    )


# ============================================================
# UPLOAD / REPLACE MEMBER PHOTO
# ============================================================

@app.route(
    "/members/<int:member_id>/upload",
    methods=["POST"]
)
@login_required
@permission_required("members.edit")
def upload_member_photo(member_id):

    db = get_db()

    member = db.execute(
        """
        SELECT
            id,
            jina_kamili,
            picha
        FROM waumini
        WHERE id = %s
        """,
        (member_id,)
    ).fetchone()

    if not member:
        abort(404)

    image = request.files.get(
        "picha"
    )

    if not image or not image.filename:

        flash(
            "Chagua picha kwanza.",
            "error"
        )

        return redirect(
            url_for(
                "edit_member",
                member_id=member_id
            )
        )

    if not allowed_file(
        image.filename
    ):

        flash(
            "Aina ya picha hairuhusiwi.",
            "error"
        )

        return redirect(
            url_for(
                "edit_member",
                member_id=member_id
            )
        )

    new_filename = (
        save_uploaded_image(image)
    )

    if not new_filename:

        flash(
            "Picha haikuweza kuhifadhiwa.",
            "error"
        )

        return redirect(
            url_for(
                "edit_member",
                member_id=member_id
            )
        )

    old_filename = member["picha"]

    db.execute(
        """
        UPDATE waumini
        SET picha = %s
        WHERE id = %s
        """,
        (
            new_filename,
            member_id
        )
    )

    delete_uploaded_file(
        old_filename
    )

    log_action(
        "UPLOAD_MEMBER_PHOTO",
        (
            "Updated photo for member ID "
            f"{member_id}"
        )
    )

    flash(
        "Picha imebadilishwa.",
        "success"
    )

    return redirect(
        url_for(
            "edit_member",
            member_id=member_id
        )
    )


# ============================================================
# CHURCH SETTINGS
# ============================================================

@app.route(
    "/settings",
    methods=["GET", "POST"]
)
@login_required
@permission_required("settings.view")
def church_settings():

    db = get_db()

    settings = get_church_settings()

    if request.method == "POST":

        if (
            not (
                get_current_admin()
                and (
                    get_current_admin()
                    .get("role_name")
                    == "superadmin"
                    or "settings.manage"
                    in get_current_admin()
                    .get(
                        "permissions",
                        set()
                    )
                )
            )
        ):

            return render_template(
                "403.html"
            ), 403

        church_name = request.form.get(
            "church_name",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        old_logo = settings["logo"]

        logo_filename = old_logo

        logo = request.files.get(
            "logo"
        )

        if logo and logo.filename:

            if not allowed_file(
                logo.filename
            ):

                flash(
                    "Aina ya logo hairuhusiwi.",
                    "error"
                )

                return render_template(
                    "settings.html",
                    settings=settings
                )

            logo_filename = (
                save_uploaded_image(
                    logo
                )
            )

            if not logo_filename:

                flash(
                    "Logo haikuweza kuhifadhiwa.",
                    "error"
                )

                return render_template(
                    "settings.html",
                    settings=settings
                )

        db.execute(
            """
            UPDATE church_settings
            SET
                church_name = %s,
                address = %s,
                phone = %s,
                email = %s,
                logo = %s
            WHERE id = 1
            """,
            (
                church_name,
                address,
                phone,
                email,
                logo_filename
            )
        )

        if (
            logo_filename != old_logo
        ):

            delete_uploaded_file(
                old_logo
            )

        log_action(
            "UPDATE_CHURCH_SETTINGS",
            "Updated church settings"
        )

        flash(
            "Mipangilio ya kanisa imehifadhiwa.",
            "success"
        )

        return redirect(
            url_for("church_settings")
        )

    return render_template(
        "settings.html",
        settings=settings
    )


# ============================================================
# SUBZONES
# ============================================================

@app.route("/subzones")
@login_required
@permission_required("subzones.view")
def subzones():

    subzone_list = (
        get_all_subzones_with_counts()
    )

    return render_template(
        "subzones.html",
        subzones=subzone_list
    )


@app.route(
    "/subzones/create",
    methods=["GET", "POST"]
)
@login_required
@permission_required("subzones.create")
def create_subzone():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        if not name:

            flash(
                "Jina la subzone linahitajika.",
                "error"
            )

            return render_template(
                "subzones.html",
                subzones=(
                    get_all_subzones_with_counts()
                )
            )

        db = get_db()

        existing = db.execute(
            """
            SELECT
                id
            FROM subzones
            WHERE LOWER(name)
                = LOWER(%s)
            """,
            (name,)
        ).fetchone()

        if existing:

            flash(
                "Subzone hiyo tayari ipo.",
                "error"
            )

            return redirect(
                url_for("subzones")
            )

        db.execute(
            """
            INSERT INTO subzones (
                name,
                description,
                active
            )
            VALUES (
                %s,
                %s,
                1
            )
            """,
            (
                name,
                description
            )
        )

        log_action(
            "CREATE_SUBZONE",
            f"Created subzone: {name}"
        )

        flash(
            "Subzone limeongezwa.",
            "success"
        )

        return redirect(
            url_for("subzones")
        )

    return render_template(
        "subzones.html",
        subzones=(
            get_all_subzones_with_counts()
        )
    )


@app.route(
    "/subzones/<int:subzone_id>/edit",
    methods=["GET", "POST"]
)
@login_required
@permission_required("subzones.edit")
def edit_subzone(subzone_id):

    db = get_db()

    subzone = db.execute(
        """
        SELECT
            id,
            name,
            description,
            active
        FROM subzones
        WHERE id = %s
        """,
        (subzone_id,)
    ).fetchone()

    if not subzone:
        abort(404)

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        if not name:

            flash(
                "Jina la subzone linahitajika.",
                "error"
            )

            return redirect(
                url_for(
                    "edit_subzone",
                    subzone_id=subzone_id
                )
            )

        duplicate = db.execute(
            """
            SELECT
                id
            FROM subzones
            WHERE LOWER(name)
                = LOWER(%s)
            AND id <> %s
            """,
            (
                name,
                subzone_id
            )
        ).fetchone()

        if duplicate:

            flash(
                "Jina hilo tayari linatumika.",
                "error"
            )

            return redirect(
                url_for(
                    "edit_subzone",
                    subzone_id=subzone_id
                )
            )

        db.execute(
            """
            UPDATE subzones
            SET
                name = %s,
                description = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                name,
                description,
                subzone_id
            )
        )

        log_action(
            "EDIT_SUBZONE",
            (
                "Edited subzone ID "
                f"{subzone_id}"
            )
        )

        flash(
            "Subzone limebadilishwa.",
            "success"
        )

        return redirect(
            url_for("subzones")
        )

    return render_template(
        "subzones.html",
        subzones=(
            get_all_subzones_with_counts()
        ),
        edit_subzone=subzone
    )


@app.route(
    "/subzones/<int:subzone_id>/delete",
    methods=["GET", "POST"]
)
@login_required
@permission_required("subzones.delete")
def delete_subzone(subzone_id):

    db = get_db()

    subzone = db.execute(
        """
        SELECT
            id,
            name
        FROM subzones
        WHERE id = %s
        """,
        (subzone_id,)
    ).fetchone()

    if not subzone:
        abort(404)

    if request.method == "POST":

        # Remove the subzone association from members.
        # This does NOT delete the members.
        db.execute(
            """
            UPDATE waumini
            SET subzone_id = NULL
            WHERE subzone_id = %s
            """,
            (subzone_id,)
        )

        # Now delete the subzone itself.
        db.execute(
            """
            DELETE FROM subzones
            WHERE id = %s
            """,
            (subzone_id,)
        )

        log_action(
            "DELETE_SUBZONE",
            (
                "Deleted subzone: "
                f"{subzone['name']}"
            )
        )

        flash(
            "Subzone imefutwa. Waumini waliokuwa ndani yake wamehifadhiwa.",
            "success"
        )

        return redirect(
            url_for("subzones")
        )

    return render_template(
        "delete.html",
        subzone=subzone
    )

@app.route(
    "/subzones/<int:subzone_id>/toggle",
    methods=["POST"]
)
@login_required
@permission_required("subzones.edit")
def toggle_subzone(subzone_id):

    db = get_db()

    subzone = db.execute(
        """
        SELECT
            id,
            name,
            active
        FROM subzones
        WHERE id = %s
        """,
        (subzone_id,)
    ).fetchone()

    if not subzone:
        abort(404)

    new_status = 0 if subzone["active"] == 1 else 1

    db.execute(
        """
        UPDATE subzones
        SET
            active = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            new_status,
            subzone_id
        )
    )

    log_action(
        "TOGGLE_SUBZONE",
        (
            f"Subzone '{subzone['name']}' "
            f"set to "
            f"{'active' if new_status == 1 else 'inactive'}"
        )
    )

    flash(
        (
            "Subzone imewezeshwa."
            if new_status == 1
            else "Subzone imezimwa."
        ),
        "success"
    )

    return redirect(
        url_for("subzones")
    )


# ============================================================
# ADMIN MANAGEMENT
# ============================================================

@app.route("/admins")
@login_required
@permission_required("admins.view")
def admins():

    db = get_db()

    admin_list = db.execute(
        """
        SELECT
            a.id,
            a.username,
            a.full_name,
            a.email,
            a.is_active,
            a.created_at,
            a.last_login,
            r.name AS role_name
        FROM admins a
        LEFT JOIN roles r
            ON r.id = a.role_id
        ORDER BY a.id ASC
        """
    ).fetchall()

    roles = db.execute(
        """
        SELECT
            id,
            name
        FROM roles
        ORDER BY
            CASE name
                WHEN 'superadmin'
                    THEN 1
                WHEN 'admin'
                    THEN 2
                WHEN 'secretary'
                    THEN 3
                WHEN 'treasurer'
                    THEN 4
                ELSE 5
            END
        """
    ).fetchall()

    return render_template(
        "admins.html",
        admins=admin_list,
        roles=roles
    )


@app.route(
    "/admins/create",
    methods=["GET", "POST"]
)
@login_required
@permission_required("admins.create")
def create_admin():

    db = get_db()

    roles = db.execute(
        """
        SELECT
            id,
            name
        FROM roles
        ORDER BY id
        """
    ).fetchall()

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        role_id = request.form.get(
            "role_id",
            ""
        ).strip()

        if not username:

            flash(
                "Username inahitajika.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        if not full_name:

            flash(
                "Jina kamili linahitajika.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        if not password:

            flash(
                "Password inahitajika.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        if len(password) < 8:

            flash(
                "Password lazima iwe na angalau herufi 8.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        try:

            role_id_int = int(
                role_id
            )

        except ValueError:

            flash(
                "Role si sahihi.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        role = db.execute(
            """
            SELECT
                id,
                name
            FROM roles
            WHERE id = %s
            """,
            (role_id_int,)
        ).fetchone()

        if not role:

            flash(
                "Role haipo.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        existing = db.execute(
            """
            SELECT
                id
            FROM admins
            WHERE LOWER(username)
                = LOWER(%s)
            """,
            (username,)
        ).fetchone()

        if existing:

            flash(
                "Username hiyo tayari ipo.",
                "error"
            )

            return render_template(
                "create_admin.html",
                roles=roles
            )

        db.execute(
            """
            INSERT INTO admins (
                username,
                password_hash,
                full_name,
                email,
                role_id,
                is_active
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                TRUE
            )
            """,
            (
                username,
                generate_password_hash(
                    password
                ),
                full_name,
                email,
                role_id_int
            )
        )

        log_action(
            "CREATE_ADMIN",
            (
                "Created admin: "
                f"{username}"
            )
        )

        flash(
            "Admin ameundwa.",
            "success"
        )

        return redirect(
            url_for("admins")
        )

    return render_template(
        "create_admin.html",
        roles=roles
    )


@app.route(
    "/admins/<int:admin_id>/toggle",
    methods=["POST"]
)
@login_required
@permission_required("admins.manage")
def toggle_admin(admin_id):

    db = get_db()

    current_admin = get_current_admin()

    if (
        current_admin
        and current_admin["id"]
        == admin_id
    ):

        flash(
            "Huwezi kubadilisha status yako mwenyewe.",
            "error"
        )

        return redirect(
            url_for("admins")
        )

    admin = db.execute(
        """
        SELECT
            id,
            username,
            is_active
        FROM admins
        WHERE id = %s
        """,
        (admin_id,)
    ).fetchone()

    if not admin:
        abort(404)

    new_status = not admin["is_active"]

    db.execute(
        """
        UPDATE admins
        SET
            is_active = %s
        WHERE id = %s
        """,
        (
            new_status,
            admin_id
        )
    )

    action = (
        "ACTIVATE_ADMIN"
        if new_status
        else "DEACTIVATE_ADMIN"
    )

    log_action(
        action,
        (
            f"Changed admin "
            f"{admin['username']} "
            f"active status to "
            f"{new_status}"
        )
    )

    flash(
        "Status ya admin imebadilishwa.",
        "success"
    )

    return redirect(
        url_for("admins")
    )


# ============================================================
# CHANGE PASSWORD
# ============================================================

@app.route(
    "/change-password",
    methods=["GET", "POST"]
)
@login_required
def change_password():

    if request.method == "POST":

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        admin = get_current_admin()

        db = get_db()

        stored_admin = db.execute(
            """
            SELECT
                id,
                password_hash
            FROM admins
            WHERE id = %s
            """,
            (admin["id"],)
        ).fetchone()

        if not stored_admin:

            session.clear()

            return redirect(
                url_for("login")
            )

        if not check_password_hash(
            stored_admin["password_hash"],
            current_password
        ):

            flash(
                "Password ya sasa si sahihi.",
                "error"
            )

            return render_template(
                "change_password.html"
            )

        if len(new_password) < 8:

            flash(
                "Password mpya lazima iwe na angalau herufi 8.",
                "error"
            )

            return render_template(
                "change_password.html"
            )

        if (
            new_password
            != confirm_password
        ):

            flash(
                "Password mpya hazifanani.",
                "error"
            )

            return render_template(
                "change_password.html"
            )

        db.execute(
            """
            UPDATE admins
            SET
                password_hash = %s
            WHERE id = %s
            """,
            (
                generate_password_hash(
                    new_password
                ),
                admin["id"]
            )
        )

        log_action(
            "CHANGE_PASSWORD",
            "Admin changed password"
        )

        flash(
            "Password imebadilishwa.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "change_password.html"
    )


# ============================================================
# AUDIT LOGS
# ============================================================

@app.route("/audit-logs")
@login_required
@permission_required("audit.view")
def audit_logs():

    db = get_db()

    logs = db.execute(
        """
        SELECT
            l.id,
            l.action,
            l.description,
            l.ip_address,
            l.created_at,
            a.username,
            a.full_name
        FROM audit_logs l
        LEFT JOIN admins a
            ON a.id = l.admin_id
        ORDER BY
            l.created_at DESC,
            l.id DESC
        """
    ).fetchall()

    return render_template(
        "audit_logs.html",
        logs=logs
    )


# ============================================================
# ANNOUNCEMENTS
# ============================================================


@app.route("/announcements")
@login_required
@permission_required(
    "announcements.view"
)
def announcements():

    db = get_db()

    announcement_list = db.execute(
        """
        SELECT
            id,
            title,
            content,
            published,
            image,
            created_at,
            updated_at
        FROM announcements
        ORDER BY
            created_at DESC
        """
    ).fetchall()

    return render_template(
        "announcements.html",
        announcements=announcement_list
    )



@app.route(
    "/announcements/create",
    methods=["GET", "POST"]
)
@login_required
@permission_required(
    "announcements.create"
)

def create_announcement():

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        publish = (
            request.form.get(
                "published"
            ) == "on"
        )

        form_data = {
            "title": title,
            "content": content,
            "published": publish
        }

        if not title:

            flash(
                "Kichwa cha tangazo kinahitajika.",
                "error"
            )

            return render_template(
                "create_announcement.html",
                form_data=form_data,
                editing=False
            )

        if not content:

            flash(
                "Maudhui ya tangazo yanahitajika.",
                "error"
            )

            return render_template(
                "create_announcement.html",
                form_data=form_data,
                editing=False
            )

        image_file = request.files.get("image")

        image_filename = None

        if image_file and image_file.filename:

            image_filename = save_uploaded_image(
                image_file
            )

            if not image_filename:

                flash(
                    "Picha haikukubalika. Tumia JPG, JPEG, PNG au WEBP chini ya 5MB.",
                    "error"
                )

                return render_template(
                    "create_announcement.html",
                    form_data=form_data,
                    editing=False
                )

        db = get_db()

        db.execute(
            """
            INSERT INTO announcements (
                title,
                content,
                published,
                image
            )
            VALUES (
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                title,
                content,
                publish,
                image_filename
            )
        )

        log_action(
            "CREATE_ANNOUNCEMENT",
            (
                "Created announcement: "
                f"{title}"
            )
        )

        flash(
            "Tangazo limeongezwa.",
            "success"
        )

        return redirect(
            url_for("announcements")
        )

    return render_template(
        "create_announcement.html",
        form_data=None,
        editing=False
    )




@app.route(
    "/announcements/<int:announcement_id>/edit",
    methods=["GET", "POST"]
)
@login_required
@permission_required(
    "announcements.edit"
)

def edit_announcement(
    announcement_id
):

    db = get_db()

    announcement = db.execute(
        """
        SELECT
            id,
            title,
            content,
            published,
            image,
            created_at,
            updated_at
        FROM announcements
        WHERE id = %s
        """,
        (announcement_id,)
    ).fetchone()

    if not announcement:
        abort(404)

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        publish = (
            request.form.get(
                "published"
            ) == "on"
        )

        form_data = {
            "title": title,
            "content": content,
            "published": publish
        }

        if not title:

            flash(
                "Kichwa cha tangazo kinahitajika.",
                "error"
            )

            return render_template(
                "create_announcement.html",
                announcement=announcement,
                form_data=form_data,
                editing=True
            )

        if not content:

            flash(
                "Maudhui ya tangazo yanahitajika.",
                "error"
            )

            return render_template(
                "create_announcement.html",
                announcement=announcement,
                form_data=form_data,
                editing=True
            )

        image_file = request.files.get("image")

        image_filename = announcement["image"]

        if image_file and image_file.filename:

            new_image_filename = save_uploaded_image(
                image_file
            )

            if not new_image_filename:

                flash(
                    "Picha haikukubalika. Tumia JPG, JPEG, PNG au WEBP chini ya 5MB.",
                    "error"
                )

                return render_template(
                    "create_announcement.html",
                    announcement=announcement,
                    form_data=form_data,
                    editing=True
                )

            if announcement["image"]:

                delete_uploaded_file(
                    announcement["image"]
                )

            image_filename = new_image_filename

        db.execute(
            """
            UPDATE announcements
            SET
                title = %s,
                content = %s,
                published = %s,
                image = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                title,
                content,
                publish,
                image_filename,
                announcement_id
            )
        )

        log_action(
            "EDIT_ANNOUNCEMENT",
            (
                "Edited announcement ID "
                f"{announcement_id}"
            )
        )

        flash(
            "Tangazo limebadilishwa.",
            "success"
        )

        return redirect(
            url_for("announcements")
        )

    return render_template(
        "create_announcement.html",
        announcement=announcement,
        form_data=None,
        editing=True
    )




@app.route(
    "/announcements/<int:announcement_id>/toggle",
    methods=["POST"]
)
@login_required
@permission_required(
    "announcements.edit"
)
def toggle_announcement(
    announcement_id
):

    db = get_db()

    announcement = db.execute(
        """
        SELECT
            id,
            title,
            published
        FROM announcements
        WHERE id = %s
        """,
        (announcement_id,)
    ).fetchone()

    if not announcement:
        abort(404)

    new_status = (
        not announcement["published"]
    )

    db.execute(
        """
        UPDATE announcements
        SET
            published = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            new_status,
            announcement_id
        )
    )

    action = (
        "PUBLISH_ANNOUNCEMENT"
        if new_status
        else "UNPUBLISH_ANNOUNCEMENT"
    )

    log_action(
        action,
        (
            f"Changed announcement ID "
            f"{announcement_id} "
            f"published status to "
            f"{new_status}"
        )
    )

    if new_status:

        flash(
            "Tangazo limechapishwa.",
            "success"
        )

    else:

        flash(
            "Tangazo limeondolewa kwenye ukurasa wa umma.",
            "success"
        )

    return redirect(
        url_for("announcements")
    )
# ============================================================
# GROUPS
# ============================================================
# ============================================================
# CREATE GROUP
# ============================================================

@app.route(
    "/groups/create",
    methods=["GET", "POST"]
)
@login_required
@permission_required("groups.create")
def create_group():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        leader = request.form.get(
            "leader",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        if not name:

            flash(
                "Jina la group linahitajika.",
                "error"
            )

            return render_template(
                "create_group.html"
            )

        existing = get_db().execute(
            """
            SELECT id
            FROM groups
            WHERE LOWER(name) = LOWER(%s)
            """,
            (name,)
        ).fetchone()

        if existing:

            flash(
                "Group hilo tayari lipo.",
                "error"
            )

            return render_template(
                "create_group.html"
            )

        db = get_db()

        db.execute(
            """
            INSERT INTO groups (
                name,
                description,
                leader,
                phone,
                is_active
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                TRUE
            )
            """,
            (
                name,
                description or None,
                leader or None,
                phone or None
            )
        )

        log_action(
            "CREATE_GROUP",
            f"Created group: {name}"
        )

        db.connection.commit()

        flash(
            "Group limeundwa.",
            "success"
        )

        return redirect(
            url_for("groups")
        )

    return render_template(
        "create_group.html"
    )


# ============================================================
# EDIT GROUP
# ============================================================

@app.route(
    "/groups/<int:group_id>/edit",
    methods=["GET", "POST"]
)
@login_required
@permission_required("groups.edit")
def edit_group(group_id):

    db = get_db()

    group = db.execute(
        """
        SELECT
            id,
            name,
            description,
            leader,
            phone,
            is_active
        FROM groups
        WHERE id = %s
        """,
        (group_id,)
    ).fetchone()

    if not group:
        return render_template(
            "404.html"
        ), 404

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        leader = request.form.get(
            "leader",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        if not name:

            flash(
                "Jina la group linahitajika.",
                "error"
            )

            return render_template(
                "edit_group.html",
                group=group
            )

        existing = db.execute(
            """
            SELECT id
            FROM groups
            WHERE LOWER(name) = LOWER(%s)
            AND id != %s
            """,
            (
                name,
                group_id
            )
        ).fetchone()

        if existing:

            flash(
                "Group hilo tayari lipo.",
                "error"
            )

            return render_template(
                "edit_group.html",
                group=group
            )

        db.execute(
            """
            UPDATE groups
            SET
                name = %s,
                description = %s,
                leader = %s,
                phone = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                name,
                description or None,
                leader or None,
                phone or None,
                group_id
            )
        )

        log_action(
            "EDIT_GROUP",
            f"Edited group: {name}"
        )

        db.commit()

        flash(
            "Group limehaririwa.",
            "success"
        )

        return redirect(
            url_for("groups")
        )

    return render_template(
        "edit_group.html",
        group=group
    )


# ============================================================
# DELETE GROUP
# ============================================================

@app.route(
    "/groups/<int:group_id>/delete",
    methods=["GET", "POST"]
)
@login_required
@permission_required("groups.delete")
def delete_group(group_id):

    db = get_db()

    group = db.execute(
        """
        SELECT
            id,
            name,
            description,
            leader,
            phone,
            is_active
        FROM groups
        WHERE id = %s
        """,
        (group_id,)
    ).fetchone()

    if not group:
        return render_template(
            "404.html"
        ), 404

    if request.method == "POST":

        db.execute(
            """
            DELETE FROM groups
            WHERE id = %s
            """,
            (group_id,)
        )

        log_action(
            "DELETE_GROUP",
            f"Deleted group: {group['name']}"
        )

        db.commit()

        flash(
            "Group limefutwa.",
            "success"
        )

        return redirect(
            url_for("groups")
        )

    return render_template(
        "delete_group.html",
        group=group
    )

# ============================================================
# GROUP MEMBERS
# ============================================================

@app.route(
    "/groups/<int:group_id>/members",
    methods=["GET", "POST"]
)
@login_required
@permission_required("groups.edit")
def group_members(group_id):

    db = get_db()

    # Get the group
    group = db.execute(
        """
        SELECT
            id,
            name
        FROM groups
        WHERE id = %s
        """,
        (group_id,)
    ).fetchone()

    if not group:
        return render_template(
            "404.html"
        ), 404

    # Get all church members
    members = db.execute(
        """
        SELECT
            id,
            namba_ya_usajili,
            jina_kamili,
            namba_ya_sim
        FROM waumini
        ORDER BY jina_kamili ASC
        """
    ).fetchall()

    # Get members already assigned to this group
    assigned_members = db.execute(
        """
        SELECT
            member_id
        FROM member_groups
        WHERE group_id = %s
        """,
        (group_id,)
    ).fetchall()

    assigned_ids = {
        member["member_id"]
        for member in assigned_members
    }

    if request.method == "POST":

        selected_members = request.form.getlist(
            "member_ids"
        )

        # Remove existing assignments for this group
        db.execute(
            """
            DELETE FROM member_groups
            WHERE group_id = %s
            """,
            (group_id,)
        )

        # Add the selected members
        for member_id in selected_members:

            db.execute(
                """
                INSERT INTO member_groups (
                    member_id,
                    group_id
                )
                VALUES (
                    %s,
                    %s
                )
                ON CONFLICT (
                    member_id,
                    group_id
                )
                DO NOTHING
                """,
                (
                    member_id,
                    group_id
                )
            )

        log_action(
            "UPDATE_GROUP_MEMBERS",
            f"Updated members for group: {group['name']}"
        )

        db.commit()

        flash(
            "Wanachama wa group wamebadilishwa.",
            "success"
        )

        return redirect(
            url_for(
                "group_members",
                group_id=group_id
            )
        )

    return render_template(
        "group_members.html",
        group=group,
        members=members,
        assigned_ids=assigned_ids
    )

@app.route("/groups")
@login_required
@permission_required("groups.view")
def groups():

    db = get_db()

    groups = db.execute(
        """
        SELECT
            id,
            name,
            description,
            leader,
            phone,
            is_active,
            created_at,
            updated_at
        FROM groups
        ORDER BY name ASC
        """
    ).fetchall()

    return render_template(
        "groups.html",
        groups=groups
    )

@app.route(
    "/announcements/<int:announcement_id>/delete",
    methods=["POST"]
)
@login_required
@permission_required(
    "announcements.delete"
)
def delete_announcement(
    announcement_id
):

    db = get_db()

    announcement = db.execute(
        """
        SELECT
            id,
            title
        FROM announcements
        WHERE id = %s
        """,
        (announcement_id,)
    ).fetchone()

    if not announcement:
        abort(404)

    db.execute(
        """
        DELETE FROM announcements
        WHERE id = %s
        """,
        (announcement_id,)
    )

    log_action(
        "DELETE_ANNOUNCEMENT",
        (
            "Deleted announcement: "
            f"{announcement['title']}"
        )
    )

    flash(
        "Tangazo limefutwa.",
        "success"
    )

    return redirect(
        url_for("announcements")
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(403)
def forbidden(error):

    return render_template(
        "403.html"
    ), 403


@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


@app.errorhandler(413)
def request_entity_too_large(error):

    flash(
        "Faili ni kubwa sana. Maximum ni 5MB.",
        "error"
    )

    return redirect(
        request.referrer
        or url_for("home")
    )


@app.errorhandler(500)
def internal_server_error(error):

    return render_template(
        "error.html"
    ), 500


# ============================================================
# INITIALIZE DATABASE
# ============================================================

with app.app_context():
    init_database()


if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )