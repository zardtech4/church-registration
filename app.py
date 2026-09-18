from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, g
from datetime import datetime
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import os
import uuid
import re
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


DATABASE_URL = os.environ["DATABASE_URL"]

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=5,
    kwargs={
        "row_factory": dict_row
    },
    open=True
)


def get_db():
    if "db" not in g:
        g.db = pool.getconn()

    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        pool.putconn(db)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def init_database():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    with pool.connection() as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                PRIMARY KEY (role_id, permission_id),
                FOREIGN KEY (role_id) REFERENCES roles(id),
                FOREIGN KEY (permission_id) REFERENCES permissions(id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                role_id INTEGER,
                FOREIGN KEY (role_id) REFERENCES roles(id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                admin_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS waumini (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                namba_ya_usajili TEXT NOT NULL UNIQUE,
                jina_kamili TEXT NOT NULL,
                makazi TEXT NOT NULL,
                jinsia TEXT NOT NULL,
                picha TEXT,
                namba_ya_sim TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        roles = [
            "superadmin",
            "admin",
            "secretary",
            "treasurer"
        ]

        permissions = [
            "dashboard.view",
            "members.view",
            "members.create",
            "members.edit",
            "members.delete",
            "admins.view",
            "admins.create",
            "admins.manage",
            "audit.view"
        ]

        for role in roles:
            db.execute(
                """
                INSERT INTO roles (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                """,
                (role,)
            )

        for permission in permissions:
            db.execute(
                """
                INSERT INTO permissions (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                """,
                (permission,)
            )

        role_permissions = {
            "superadmin": permissions,

            "admin": [
                "dashboard.view",
                "members.view",
                "members.create",
                "members.edit",
                "members.delete",
                "admins.view",
                "audit.view"
            ],

            "secretary": [
                "dashboard.view",
                "members.view",
                "members.create",
                "members.edit"
            ],

            "treasurer": [
                "dashboard.view",
                "members.view"
            ]
        }

        for role_name, permission_names in role_permissions.items():

            role = db.execute(
                """
                SELECT id
                FROM roles
                WHERE name = %s
                """,
                (role_name,)
            ).fetchone()

            for permission_name in permission_names:

                permission = db.execute(
                    """
                    SELECT id
                    FROM permissions
                    WHERE name = %s
                    """,
                    (permission_name,)
                ).fetchone()

                db.execute(
                    """
                    INSERT INTO role_permissions
                    (
                        role_id,
                        permission_id
                    )
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        role["id"],
                        permission["id"]
                    )
                )

        superadmin_role = db.execute(
            """
            SELECT id
            FROM roles
            WHERE name = 'superadmin'
            """
        ).fetchone()

        existing_admin = db.execute(
            """
            SELECT id
            FROM admins
            WHERE username = 'admin'
            """
        ).fetchone()

        if not existing_admin:

            initial_password = os.environ.get(
                "INITIAL_ADMIN_PASSWORD",
                "ChangeMeImmediately123!"
            )

            db.execute(
                """
                INSERT INTO admins
                (
                    username,
                    full_name,
                    password_hash,
                    active,
                    role_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    "admin",
                    "System Administrator",
                    generate_password_hash(initial_password),
                    1,
                    superadmin_role["id"]
                )
            )

        db.execute(
            """
            UPDATE admins
            SET role_id = %s
            WHERE role_id IS NULL
            """,
            (superadmin_role["id"],)
        )

        db.commit()


init_database()


def get_current_admin():

    if hasattr(g, "current_admin"):
        return g.current_admin

    admin_id = session.get("admin_id")

    if not admin_id:
        g.current_admin = None
        g.current_permissions = set()
        return None

    db = get_db()

    admin = db.execute(
        """
        SELECT
            admins.id,
            admins.username,
            admins.full_name,
            admins.active,
            admins.created_at,
            admins.last_login,
            admins.role_id,
            roles.name AS role_name
        FROM admins
        LEFT JOIN roles
            ON admins.role_id = roles.id
        WHERE admins.id = %s
        """,
        (admin_id,)
    ).fetchone()

    if not admin:
        g.current_admin = None
        g.current_permissions = set()
        return None

    permissions = db.execute(
        """
        SELECT p.name
        FROM role_permissions rp
        JOIN permissions p
            ON rp.permission_id = p.id
        WHERE rp.role_id = %s
        """,
        (admin["role_id"],)
    ).fetchall()

    g.current_admin = admin
    g.current_permissions = {
        row["name"]
        for row in permissions
    }

    return admin


def has_permission(permission_name):

    get_current_admin()

    return permission_name in getattr(
        g,
        "current_permissions",
        set()
    )


def login_required():
    def decorator(view):

        @wraps(view)
        def wrapped(*args, **kwargs):

            admin = get_current_admin()

            if not admin:
                return redirect(url_for("login"))

            if not admin["active"]:
                session.clear()
                g.current_admin = None
                g.current_permissions = set()

                return redirect(url_for("login"))

            return view(*args, **kwargs)

        return wrapped

    return decorator


def permission_required(permission_name):

    def decorator(view):

        @wraps(view)
        def wrapped(*args, **kwargs):

            admin = get_current_admin()

            if not admin:
                return redirect(url_for("login"))

            if not admin["active"]:
                session.clear()

                return redirect(url_for("login"))

            if not has_permission(permission_name):
                return render_template(
                    "403.html"
                ), 403

            return view(*args, **kwargs)

        return wrapped

    return decorator


def log_action(action, details=None):

    admin = get_current_admin()

    if not admin:
        return

    db = get_db()

    db.execute(
        """
        INSERT INTO audit_logs
        (
            admin_id,
            action,
            details
        )
        VALUES (%s, %s, %s)
        """,
        (
            admin["id"],
            action,
            details
        )
    )

    db.commit()


def generate_registration_number():

    year = datetime.now().year

    db = get_db()

    row = db.execute(
        """
        SELECT namba_ya_usajili
        FROM waumini
        WHERE namba_ya_usajili LIKE %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"WM-{year}-%",)
    ).fetchone()

    if not row:
        return f"WM-{year}-0001"

    match = re.search(
        rf"WM-{year}-(\d+)",
        row["namba_ya_usajili"]
    )

    if not match:
        return f"WM-{year}-0001"

    number = int(match.group(1)) + 1

    return f"WM-{year}-{number:04d}"


@app.context_processor
def inject_global_variables():

    admin = get_current_admin()

    permissions = getattr(
        g,
        "current_permissions",
        set()
    )

    return {
        "current_admin": admin,

        "is_logged_in": admin is not None,

        "is_superadmin": (
            admin is not None
            and admin["role_name"] == "superadmin"
        ),

        "can_view_admins":
            "admins.view" in permissions,

        "can_create_admins":
            "admins.create" in permissions,

        "can_manage_admins":
            "admins.manage" in permissions,

        "can_view_audit":
            "audit.view" in permissions,

        "can_view_members":
            "members.view" in permissions,

        "can_edit_members":
            "members.edit" in permissions,

        "can_delete_members":
            "members.delete" in permissions
    }


@app.route("/", methods=["GET", "POST"])
def register():

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

        if not jina_kamili or not makazi or not jinsia or not namba_ya_sim:

            return render_template(
                "register.html",
                error="Tafadhali jaza sehemu zote muhimu."
            )

        picha_filename = None

        file = request.files.get("picha")

        if file and file.filename:

            if not allowed_file(file.filename):

                return render_template(
                    "register.html",
                    error="Aina ya picha hairuhusiwi."
                )

            original_name = secure_filename(
                file.filename
            )

            extension = original_name.rsplit(
                ".",
                1
            )[1].lower()

            picha_filename = (
                f"{uuid.uuid4().hex}.{extension}"
            )

            os.makedirs(
                UPLOAD_FOLDER,
                exist_ok=True
            )

            file.save(
                os.path.join(
                    UPLOAD_FOLDER,
                    picha_filename
                )
            )

        registration_number = generate_registration_number()

        db = get_db()

        try:

            db.execute(
                """
                INSERT INTO waumini
                (
                    namba_ya_usajili,
                    jina_kamili,
                    makazi,
                    jinsia,
                    picha,
                    namba_ya_sim
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    registration_number,
                    jina_kamili,
                    makazi,
                    jinsia,
                    picha_filename,
                    namba_ya_sim
                )
            )

            db.commit()

        except psycopg.IntegrityError:

            db.rollback()

            return render_template(
                "register.html",
                error="Imeshindikana kusajili mwanachama."
            )

        return render_template(
            "success.html",
            registration_number=registration_number,
            jina_kamili=jina_kamili
        )

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if get_current_admin():
        return redirect(
            url_for("dashboard")
        )

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
                admins.*,
                roles.name AS role_name
            FROM admins
            LEFT JOIN roles
                ON admins.role_id = roles.id
            WHERE admins.username = %s
            """,
            (username,)
        ).fetchone()

        if (
            admin
            and admin["active"]
            and check_password_hash(
                admin["password_hash"],
                password
            )
        ):

            session.clear()

            session["admin_id"] = admin["id"]

            db.execute(
                """
                UPDATE admins
                SET last_login = %s
                WHERE id = %s
                """,
                (
                    datetime.now(),
                    admin["id"]
                )
            )

            db.commit()

            g.current_admin = admin

            permissions = db.execute(
                """
                SELECT p.name
                FROM role_permissions rp
                JOIN permissions p
                    ON rp.permission_id = p.id
                WHERE rp.role_id = %s
                """,
                (admin["role_id"],)
            ).fetchall()

            g.current_permissions = {
                row["name"]
                for row in permissions
            }

            log_action(
                "login",
                f"Admin {username} aliingia kwenye mfumo."
            )

            return redirect(
                url_for("dashboard")
            )

        return render_template(
            "login.html",
            error="Username au password si sahihi."
        )

    return render_template("login.html")


@app.route("/logout")
def logout():

    admin = get_current_admin()

    if admin:

        log_action(
            "logout",
            f"Admin {admin['username']} alitoka kwenye mfumo."
        )

    session.clear()

    g.current_admin = None
    g.current_permissions = set()

    return redirect(
        url_for("login")
    )


@app.route("/dashboard")
@permission_required("dashboard.view")
def dashboard():

    db = get_db()

    stats = db.execute(
        """
        SELECT
            COUNT(*) AS jumla,

            COUNT(*) FILTER (
                WHERE LOWER(jinsia)
                IN ('mume', 'mwanaume', 'male')
            ) AS wanaume,

            COUNT(*) FILTER (
                WHERE LOWER(jinsia)
                IN ('mke', 'mwanamke', 'female')
            ) AS wanawake,

            COUNT(*) FILTER (
                WHERE EXTRACT(
                    YEAR FROM created_at
                ) = %s
            ) AS waliosajiliwa_mwaka_huu

        FROM waumini
        """,
        (datetime.now().year,)
    ).fetchone()

    makazi = db.execute(
        """
        SELECT
            makazi,
            COUNT(*) AS idadi
        FROM waumini
        GROUP BY makazi
        ORDER BY idadi DESC, makazi ASC
        """
    ).fetchall()

    total_admins = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM admins
        """
    ).fetchone()["total"]

    active_admins = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM admins
        WHERE active = 1
        """
    ).fetchone()["total"]

    mwaka = datetime.now().year

    return render_template(
        "dashboard.html",

        jumla=stats["jumla"],

        wanaume=stats["wanaume"],

        wanawake=stats["wanawake"],

        mwaka=mwaka,

        waliosajiliwa_mwaka_huu=
            stats["waliosajiliwa_mwaka_huu"],

        makazi=makazi,

        total_members=stats["jumla"],

        total_admins=total_admins,

        active_admins=active_admins
    )


@app.route("/members")
@permission_required("members.view")
def members():

    search = request.args.get(
        "search",
        ""
    ).strip()

    db = get_db()

    if search:

        waumini = db.execute(
            """
            SELECT *
            FROM waumini
            WHERE
                jina_kamili ILIKE %s
                OR namba_ya_usajili ILIKE %s
                OR namba_ya_sim ILIKE %s
                OR makazi ILIKE %s
            ORDER BY id DESC
            """,
            (
                f"%{search}%",
                f"%{search}%",
                f"%{search}%",
                f"%{search}%"
            )
        ).fetchall()

    else:

        waumini = db.execute(
            """
            SELECT *
            FROM waumini
            ORDER BY id DESC
            """
        ).fetchall()

    jumla = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM waumini
        """
    ).fetchone()["total"]

    return render_template(
        "members.html",
        jumla=jumla,
        waumini=waumini,
        members=waumini,
        search=search
    )


@app.route("/edit/<int:id>", methods=["GET", "POST"])
@permission_required("members.edit")
def edit_member(id):

    db = get_db()

    member = db.execute(
        """
        SELECT *
        FROM waumini
        WHERE id = %s
        """,
        (id,)
    ).fetchone()

    if not member:
        return render_template(
            "404.html"
        ), 404

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

        if not jina_kamili or not makazi or not jinsia or not namba_ya_sim:

            return render_template(
                "edit.html",
                member=member,
                error="Tafadhali jaza sehemu zote muhimu."
            )

        picha_filename = member["picha"]

        file = request.files.get("picha")

        if file and file.filename:

            if not allowed_file(file.filename):

                return render_template(
                    "edit.html",
                    member=member,
                    error="Aina ya picha hairuhusiwi."
                )

            original_name = secure_filename(
                file.filename
            )

            extension = original_name.rsplit(
                ".",
                1
            )[1].lower()

            new_filename = (
                f"{uuid.uuid4().hex}.{extension}"
            )

            file.save(
                os.path.join(
                    UPLOAD_FOLDER,
                    new_filename
                )
            )

            if picha_filename:

                old_path = os.path.join(
                    UPLOAD_FOLDER,
                    picha_filename
                )

                if os.path.exists(old_path):

                    try:
                        os.remove(old_path)

                    except OSError:
                        pass

            picha_filename = new_filename

        db.execute(
            """
            UPDATE waumini
            SET
                jina_kamili = %s,
                makazi = %s,
                jinsia = %s,
                picha = %s,
                namba_ya_sim = %s
            WHERE id = %s
            """,
            (
                jina_kamili,
                makazi,
                jinsia,
                picha_filename,
                namba_ya_sim,
                id
            )
        )

        db.commit()

        log_action(
            "edit_member",
            f"Mwanachama {id} amehaririwa."
        )

        return redirect(
            url_for("members")
        )

    return render_template(
        "edit.html",
        member=member
    )


@app.route("/delete/<int:id>", methods=["POST", "GET"])
@permission_required("members.delete")
def delete_member(id):

    db = get_db()

    member = db.execute(
        """
        SELECT *
        FROM waumini
        WHERE id = %s
        """,
        (id,)
    ).fetchone()

    if not member:
        return render_template(
            "404.html"
        ), 404

    if member["picha"]:

        image_path = os.path.join(
            UPLOAD_FOLDER,
            member["picha"]
        )

        if os.path.exists(image_path):

            try:
                os.remove(image_path)

            except OSError:
                pass

    db.execute(
        """
        DELETE FROM waumini
        WHERE id = %s
        """,
        (id,)
    )

    db.commit()

    log_action(
        "delete_member",
        f"Mwanachama {id} amefutwa."
    )

    return redirect(
        url_for("members")
    )


@app.route("/uploads/<filename>")
def uploaded_file(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename
    )


@app.route("/admins")
@permission_required("admins.view")
def admins():

    db = get_db()

    admin_list = db.execute(
        """
        SELECT
            admins.id,
            admins.username,
            admins.full_name,
            admins.active,
            admins.created_at,
            admins.last_login,
            roles.name AS role_name
        FROM admins
        LEFT JOIN roles
            ON admins.role_id = roles.id
        ORDER BY admins.id DESC
        """
    ).fetchall()

    return render_template(
        "admins.html",
        admins=admin_list
    )


@app.route("/admins/create", methods=["GET", "POST"])
@permission_required("admins.create")
def create_admin():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        role_name = request.form.get(
            "role",
            ""
        ).strip()

        if not username or not full_name or not password or not role_name:

            return render_template(
                "create_admin.html",
                error="Tafadhali jaza sehemu zote."
            )

        db = get_db()

        role = db.execute(
            """
            SELECT id
            FROM roles
            WHERE name = %s
            """,
            (role_name,)
        ).fetchone()

        if not role:

            return render_template(
                "create_admin.html",
                error="Role haipo."
            )

        existing = db.execute(
            """
            SELECT id
            FROM admins
            WHERE username = %s
            """,
            (username,)
        ).fetchone()

        if existing:

            return render_template(
                "create_admin.html",
                error="Username tayari ipo."
            )

        db.execute(
            """
            INSERT INTO admins
            (
                username,
                full_name,
                password_hash,
                active,
                role_id
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                username,
                full_name,
                generate_password_hash(password),
                1,
                role["id"]
            )
        )

        db.commit()

        log_action(
            "create_admin",
            f"Admin mpya {username} ameundwa."
        )

        return redirect(
            url_for("admins")
        )

    return render_template(
        "create_admin.html"
    )


@app.route("/admins/<int:id>/activate", methods=["POST"])
@permission_required("admins.manage")
def activate_admin(id):

    db = get_db()

    admin = db.execute(
        """
        SELECT username
        FROM admins
        WHERE id = %s
        """,
        (id,)
    ).fetchone()

    if not admin:
        return render_template(
            "404.html"
        ), 404

    db.execute(
        """
        UPDATE admins
        SET active = 1
        WHERE id = %s
        """,
        (id,)
    )

    db.commit()

    log_action(
        "activate_admin",
        f"Admin {admin['username']} amewezeshwa."
    )

    return redirect(
        url_for("admins")
    )


@app.route("/admins/<int:id>/deactivate", methods=["POST"])
@permission_required("admins.manage")
def deactivate_admin(id):

    current_admin = get_current_admin()

    if current_admin and current_admin["id"] == id:
        return redirect(
            url_for("admins")
        )

    db = get_db()

    admin = db.execute(
        """
        SELECT username
        FROM admins
        WHERE id = %s
        """,
        (id,)
    ).fetchone()

    if not admin:
        return render_template(
            "404.html"
        ), 404

    db.execute(
        """
        UPDATE admins
        SET active = 0
        WHERE id = %s
        """,
        (id,)
    )

    db.commit()

    log_action(
        "deactivate_admin",
        f"Admin {admin['username']} amezimwa."
    )

    return redirect(
        url_for("admins")
    )


@app.route("/change-password", methods=["GET", "POST"])
@login_required()
def change_password():

    admin = get_current_admin()

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

        db = get_db()

        row = db.execute(
            """
            SELECT password_hash
            FROM admins
            WHERE id = %s
            """,
            (admin["id"],)
        ).fetchone()

        if not row or not check_password_hash(
            row["password_hash"],
            current_password
        ):

            return render_template(
                "change_password.html",
                error="Password ya sasa si sahihi."
            )

        if len(new_password) < 8:

            return render_template(
                "change_password.html",
                error="Password mpya lazima iwe na angalau herufi 8."
            )

        if new_password != confirm_password:

            return render_template(
                "change_password.html",
                error="Password mpya hazifanani."
            )

        db.execute(
            """
            UPDATE admins
            SET password_hash = %s
            WHERE id = %s
            """,
            (
                generate_password_hash(new_password),
                admin["id"]
            )
        )

        db.commit()

        log_action(
            "change_password",
            "Admin amebadilisha password yake."
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "change_password.html"
    )


@app.route("/audit-logs")
@permission_required("audit.view")
def audit_logs():

    db = get_db()

    logs = db.execute(
        """
        SELECT
            audit_logs.id,
            audit_logs.action,
            audit_logs.details,
            audit_logs.created_at,
            admins.username,
            admins.full_name
        FROM audit_logs
        LEFT JOIN admins
            ON audit_logs.admin_id = admins.id
        ORDER BY audit_logs.id DESC
        """
    ).fetchall()

    return render_template(
        "audit_logs.html",
        logs=logs
    )


@app.errorhandler(403)
def forbidden(error):

    return render_template(
        "403.html"
    ), 403


@app.errorhandler(404)
def not_found(error):

    return render_template(
        "404.html"
    ), 404


@app.errorhandler(413)
def too_large(error):

    return render_template(
        "error.html",
        message="Faili ni kubwa sana."
    ), 413


@app.errorhandler(500)
def server_error(error):

    return render_template(
        "error.html",
        message="Hitilafu ya mfumo imetokea."
    ), 500


if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )