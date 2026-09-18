from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from datetime import datetime
import sqlite3
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "church.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def init_database():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT NOT NULL,
            description TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            details TEXT
        )
    """)

    admin_columns = [
        row["name"]
        for row in db.execute("PRAGMA table_info(admins)").fetchall()
    ]

    if "role_id" not in admin_columns:
        db.execute("ALTER TABLE admins ADD COLUMN role_id INTEGER")

    roles = [
        (
            "superadmin",
            "Full access to the church management system."
        ),
        (
            "admin",
            "General administrative access."
        ),
        (
            "secretary",
            "Member and church administration."
        ),
        (
            "treasurer",
            "Financial administration."
        )
    ]

    for name, description in roles:
        db.execute(
            """
            INSERT OR IGNORE INTO roles (name, description)
            VALUES (?, ?)
            """,
            (name, description)
        )

    permissions = [
        (
            "dashboard.view",
            "View the administration dashboard."
        ),
        (
            "members.view",
            "View registered members."
        ),
        (
            "members.create",
            "Register new members."
        ),
        (
            "members.edit",
            "Edit member information."
        ),
        (
            "members.delete",
            "Delete members."
        ),
        (
            "admins.view",
            "View administrators."
        ),
        (
            "admins.create",
            "Create administrators."
        ),
        (
            "admins.manage",
            "Activate or deactivate administrators."
        ),
        (
            "audit.view",
            "View audit logs."
        )
    ]

    for name, description in permissions:
        db.execute(
            """
            INSERT OR IGNORE INTO permissions (name, description)
            VALUES (?, ?)
            """,
            (name, description)
        )

    role_permissions = {
        "superadmin": [
            "dashboard.view",
            "members.view",
            "members.create",
            "members.edit",
            "members.delete",
            "admins.view",
            "admins.create",
            "admins.manage",
            "audit.view"
        ],
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
            "dashboard.view"
        ]
    }

    for role_name, permission_names in role_permissions.items():
        role = db.execute(
            "SELECT id FROM roles WHERE name = ?",
            (role_name,)
        ).fetchone()

        if not role:
            continue

        for permission_name in permission_names:
            permission = db.execute(
                "SELECT id FROM permissions WHERE name = ?",
                (permission_name,)
            ).fetchone()

            if permission:
                db.execute(
                    """
                    INSERT OR IGNORE INTO role_permissions
                    (role_id, permission_id)
                    VALUES (?, ?)
                    """,
                    (role["id"], permission["id"])
                )

    admin = db.execute(
        "SELECT id FROM admins WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin:
        initial_password = os.environ.get(
            "INITIAL_ADMIN_PASSWORD",
            "ChangeMeImmediately123!"
        )

        superadmin_role = db.execute(
            "SELECT id FROM roles WHERE name = ?",
            ("superadmin",)
        ).fetchone()

        db.execute(
            """
            INSERT INTO admins
            (
                username,
                full_name,
                password_hash,
                role,
                role_id,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                "admin",
                "System Administrator",
                generate_password_hash(initial_password),
                "superadmin",
                superadmin_role["id"]
            )
        )

    db.execute(
        """
        UPDATE admins
        SET role_id = (
            SELECT id
            FROM roles
            WHERE roles.name = admins.role
        )
        WHERE role_id IS NULL
        """
    )

    db.commit()
    db.close()


def get_current_admin():
    admin_id = session.get("admin_id")

    if not admin_id:
        return None

    db = get_db()

    admin = db.execute(
        """
        SELECT
            admins.*,
            roles.name AS role_name,
            roles.description AS role_description
        FROM admins
        LEFT JOIN roles
            ON admins.role_id = roles.id
        WHERE admins.id = ?
          AND admins.is_active = 1
        """,
        (admin_id,)
    ).fetchone()

    db.close()

    return admin


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        admin = get_current_admin()

        if not admin:
            session.clear()

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return view(*args, **kwargs)

    return wrapped_view


def has_permission(permission_name):
    admin = get_current_admin()

    if not admin:
        return False

    if admin["role_name"] == "superadmin":
        return True

    db = get_db()

    permission = db.execute(
        """
        SELECT 1
        FROM role_permissions
        JOIN permissions
            ON role_permissions.permission_id = permissions.id
        WHERE role_permissions.role_id = ?
          AND permissions.name = ?
        """,
        (
            admin["role_id"],
            permission_name
        )
    ).fetchone()

    db.close()

    return permission is not None


def permission_required(permission_name):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not get_current_admin():
                session.clear()

                return redirect(
                    url_for(
                        "login",
                        next=request.path
                    )
                )

            if not has_permission(permission_name):
                return render_template(
                    "403.html"
                ), 403

            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def log_action(
    action,
    description=None,
    details=None,
    admin_id=None
):
    db = get_db()

    if admin_id is None:
        admin = get_current_admin()

        if admin:
            admin_id = admin["id"]

    db.execute(
        """
        INSERT INTO audit_logs
        (
            admin_id,
            action,
            description,
            ip_address,
            details
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            admin_id,
            action,
            description,
            request.remote_addr,
            details
        )
    )

    db.commit()
    db.close()


def generate_registration_number(db):
    current_year = datetime.now().year

    rows = db.execute(
        """
        SELECT namba_ya_usajili
        FROM waumini
        WHERE namba_ya_usajili LIKE ?
        """,
        (f"{current_year}.%",)
    ).fetchall()

    highest = 0

    for row in rows:
        value = row["namba_ya_usajili"]

        if not value:
            continue

        match = re.match(
            rf"^{current_year}\.(\d+)$",
            str(value)
        )

        if match:
            number = int(match.group(1))

            if number > highest:
                highest = number

    return f"{current_year}.{highest + 1:04d}"


@app.context_processor
def inject_global_variables():
    admin = get_current_admin()

    return {
        "current_admin": admin,
        "is_logged_in": admin is not None,
        "is_superadmin": (
            admin is not None
            and admin["role_name"] == "superadmin"
        ),
        "can_view_admins": has_permission("admins.view"),
        "can_create_admins": has_permission("admins.create"),
        "can_manage_admins": has_permission("admins.manage"),
        "can_view_audit": has_permission("audit.view"),
        "can_view_members": has_permission("members.view"),
        "can_edit_members": has_permission("members.edit"),
        "can_delete_members": has_permission("members.delete")
    }


@app.route("/", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template(
            "register.html",
            error=None,
            form_data=None
        )

    jina_kamili = request.form.get(
        "jina_kamili",
        ""
    ).strip()

    makazi = request.form.get(
        "makazi",
        ""
    ).strip()

    namba_ya_sim = request.form.get(
        "namba_ya_sim",
        ""
    ).strip()

    jinsia = request.form.get(
        "jinsia",
        ""
    ).strip()

    form_data = {
        "jina_kamili": jina_kamili,
        "makazi": makazi,
        "namba_ya_sim": namba_ya_sim,
        "jinsia": jinsia
    }

    if not jina_kamili:
        return render_template(
            "register.html",
            error="Jina kamili linahitajika.",
            form_data=form_data
        )

    if not makazi:
        return render_template(
            "register.html",
            error="Makazi yanahitajika.",
            form_data=form_data
        )

    if not namba_ya_sim:
        return render_template(
            "register.html",
            error="Namba ya simu inahitajika.",
            form_data=form_data
        )

    if jinsia not in ["Mwanaume", "Mwanamke"]:
        return render_template(
            "register.html",
            error="Chagua jinsia sahihi.",
            form_data=form_data
        )

    db = get_db()

    registration_number = generate_registration_number(db)

    photo_filename = None

    file = request.files.get("picha")

    if file and file.filename:
        if not allowed_file(file.filename):
            db.close()

            return render_template(
                "register.html",
                error="Aina ya picha hairuhusiwi.",
                form_data=form_data
            )

        original_name = secure_filename(
            file.filename
        )

        extension = original_name.rsplit(
            ".",
            1
        )[1].lower()

        photo_filename = (
            f"{uuid.uuid4().hex}.{extension}"
        )

        file.save(
            os.path.join(
                UPLOAD_FOLDER,
                photo_filename
            )
        )

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
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            registration_number,
            jina_kamili,
            makazi,
            jinsia,
            photo_filename,
            namba_ya_sim
        )
    )

    member_id = db.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    db.commit()
    db.close()

    admin = get_current_admin()

    if admin:
        log_action(
            "member_created",
            f"Member {jina_kamili} registered.",
            f"Member ID: {member_id}; Registration: {registration_number}"
        )

        return redirect(
            url_for("members")
        )

    log_action(
        "public_member_registered",
        f"Public registration for {jina_kamili}.",
        f"Member ID: {member_id}; Registration: {registration_number}"
    )

    return render_template(
        "success.html",
        jina=jina_kamili,
        registration_number=registration_number
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_admin():
        return redirect(
            url_for("dashboard")
        )

    if request.method == "GET":
        return render_template(
            "login.html",
            error=None
        )

    username = request.form.get(
        "username",
        ""
    ).strip()

    password = request.form.get(
        "password",
        ""
    )

    if not username or not password:
        return render_template(
            "login.html",
            error="Ingiza username na password."
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
        WHERE admins.username = ?
        """,
        (username,)
    ).fetchone()

    if not admin:
        db.close()

        return render_template(
            "login.html",
            error="Username au password si sahihi."
        )

    if not admin["is_active"]:
        db.close()

        return render_template(
            "login.html",
            error="Akaunti hii imezuiwa."
        )

    if not check_password_hash(
        admin["password_hash"],
        password
    ):
        db.close()

        return render_template(
            "login.html",
            error="Username au password si sahihi."
        )

    db.execute(
        """
        UPDATE admins
        SET last_login = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (admin["id"],)
    )

    db.commit()
    db.close()

    session.clear()
    session["admin_id"] = admin["id"]

    log_action(
        "login",
        f"Administrator {admin['username']} logged in."
    )

    next_url = request.args.get("next")

    if next_url and next_url.startswith("/"):
        return redirect(next_url)

    return redirect(
        url_for("dashboard")
    )


@app.route("/logout")
@login_required
def logout():
    admin = get_current_admin()

    if admin:
        log_action(
            "logout",
            f"Administrator {admin['username']} logged out."
        )

    session.clear()

    return redirect(
        url_for("login")
    )


@app.route("/dashboard")
@login_required
@permission_required("dashboard.view")
def dashboard():
    db = get_db()

    total_members = db.execute(
        "SELECT COUNT(*) AS total FROM waumini"
    ).fetchone()["total"]

    male_members = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM waumini
        WHERE jinsia = ?
        """,
        ("Mwanaume",)
    ).fetchone()["total"]

    female_members = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM waumini
        WHERE jinsia = ?
        """,
        ("Mwanamke",)
    ).fetchone()["total"]

    current_year = datetime.now().year

    registered_this_year = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM waumini
        WHERE namba_ya_usajili LIKE ?
        """,
        (f"{current_year}.%",)
    ).fetchone()["total"]

    area_counts = db.execute(
        """
        SELECT
            TRIM(makazi) AS makazi,
            COUNT(*) AS idadi
        FROM waumini
        WHERE TRIM(COALESCE(makazi, '')) != ''
        GROUP BY LOWER(TRIM(makazi))
        ORDER BY idadi DESC, makazi ASC
        """
    ).fetchall()

    total_admins = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM admins
        WHERE is_active = 1
        """
    ).fetchone()["total"]

    recent_members = db.execute(
        """
        SELECT *
        FROM waumini
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

    db.close()

    return render_template(
        "dashboard.html",
        jumla=total_members,
        wanaume=male_members,
        wanawake=female_members,
        mwaka=current_year,
        waliosajiliwa_mwaka_huu=registered_this_year,
        makazi=area_counts,
        total_members=total_members,
        male_members=male_members,
        female_members=female_members,
        area_counts=area_counts,
        total_admins=total_admins,
        recent_members=recent_members,
        waumini=recent_members
    )


@app.route("/members")
@login_required
@permission_required("members.view")
def members():
    search = request.args.get(
        "search",
        ""
    ).strip()

    db = get_db()

    if search:
        search_value = f"%{search}%"

        waumini = db.execute(
            """
            SELECT *
            FROM waumini
            WHERE
                jina_kamili LIKE ?
                OR makazi LIKE ?
                OR namba_ya_sim LIKE ?
                OR namba_ya_usajili LIKE ?
            ORDER BY id DESC
            """,
            (
                search_value,
                search_value,
                search_value,
                search_value
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
        "SELECT COUNT(*) AS total FROM waumini"
    ).fetchone()["total"]

    db.close()

    return render_template(
        "members.html",
        waumini=waumini,
        jumla=jumla,
        search=search
    )


@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
@permission_required("members.edit")
def edit(id):
    db = get_db()

    mtu = db.execute(
        """
        SELECT *
        FROM waumini
        WHERE id = ?
        """,
        (id,)
    ).fetchone()

    if not mtu:
        db.close()

        return render_template(
            "404.html"
        ), 404

    if request.method == "GET":
        db.close()

        return render_template(
            "edit.html",
            mtu=mtu
        )

    jina_kamili = request.form.get(
        "jina_kamili",
        ""
    ).strip()

    makazi = request.form.get(
        "makazi",
        ""
    ).strip()

    namba_ya_sim = request.form.get(
        "namba_ya_sim",
        ""
    ).strip()

    jinsia = request.form.get(
        "jinsia",
        ""
    ).strip()

    if not jina_kamili or not makazi or not namba_ya_sim:
        db.close()

        return render_template(
            "edit.html",
            mtu=mtu,
            error="Tafadhali jaza taarifa zote zinazohitajika."
        )

    photo_filename = mtu["picha"]

    file = request.files.get("picha")

    if file and file.filename:
        if not allowed_file(file.filename):
            db.close()

            return render_template(
                "edit.html",
                mtu=mtu,
                error="Aina ya picha hairuhusiwi."
            )

        original_name = secure_filename(
            file.filename
        )

        extension = original_name.rsplit(
            ".",
            1
        )[1].lower()

        new_photo_filename = (
            f"{uuid.uuid4().hex}.{extension}"
        )

        file.save(
            os.path.join(
                UPLOAD_FOLDER,
                new_photo_filename
            )
        )

        if photo_filename:
            old_photo_path = os.path.join(
                UPLOAD_FOLDER,
                photo_filename
            )

            if os.path.exists(old_photo_path):
                try:
                    os.remove(old_photo_path)
                except OSError:
                    pass

        photo_filename = new_photo_filename

    db.execute(
        """
        UPDATE waumini
        SET
            jina_kamili = ?,
            makazi = ?,
            jinsia = ?,
            picha = ?,
            namba_ya_sim = ?
        WHERE id = ?
        """,
        (
            jina_kamili,
            makazi,
            jinsia,
            photo_filename,
            namba_ya_sim,
            id
        )
    )

    db.commit()
    db.close()

    log_action(
        "member_updated",
        f"Member {jina_kamili} updated.",
        f"Member ID: {id}"
    )

    return redirect(
        url_for("members")
    )


@app.route("/delete/<int:id>", methods=["GET", "POST"])
@login_required
@permission_required("members.delete")
def delete(id):
    db = get_db()

    mtu = db.execute(
        """
        SELECT *
        FROM waumini
        WHERE id = ?
        """,
        (id,)
    ).fetchone()

    if not mtu:
        db.close()

        return render_template(
            "404.html"
        ), 404

    if request.method == "GET":
        db.close()

        return render_template(
            "delete.html",
            mtu=mtu
        )

    photo_filename = mtu["picha"]

    db.execute(
        """
        DELETE FROM waumini
        WHERE id = ?
        """,
        (id,)
    )

    db.commit()
    db.close()

    if photo_filename:
        photo_path = os.path.join(
            UPLOAD_FOLDER,
            photo_filename
        )

        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError:
                pass

    log_action(
        "member_deleted",
        f"Member {mtu['jina_kamili']} deleted.",
        f"Member ID: {id}; Registration: {mtu['namba_ya_usajili']}"
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
@login_required
@permission_required("admins.view")
def admins():
    db = get_db()

    administrator_list = db.execute(
        """
        SELECT
            admins.*,
            roles.name AS role_name,
            roles.description AS role_description
        FROM admins
        LEFT JOIN roles
            ON admins.role_id = roles.id
        ORDER BY admins.id ASC
        """
    ).fetchall()

    db.close()

    return render_template(
        "admins.html",
        admins=administrator_list
    )


@app.route("/admins/create", methods=["GET", "POST"])
@login_required
@permission_required("admins.create")
def create_admin():
    if request.method == "GET":
        return render_template(
            "create_admin.html",
            error=None,
            form_data=None
        )

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

    role_name = request.form.get(
        "role",
        "admin"
    ).strip()

    form_data = {
        "username": username,
        "full_name": full_name,
        "email": email,
        "role": role_name
    }

    if not username or not full_name or not password:
        return render_template(
            "create_admin.html",
            error="Username, jina kamili na password vinahitajika.",
            form_data=form_data
        )

    if len(password) < 8:
        return render_template(
            "create_admin.html",
            error="Password lazima iwe na angalau characters 8.",
            form_data=form_data
        )

    db = get_db()

    role = db.execute(
        """
        SELECT *
        FROM roles
        WHERE name = ?
        """,
        (role_name,)
    ).fetchone()

    if not role:
        db.close()

        return render_template(
            "create_admin.html",
            error="Role hiyo haipo.",
            form_data=form_data
        )

    existing = db.execute(
        """
        SELECT id
        FROM admins
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if existing:
        db.close()

        return render_template(
            "create_admin.html",
            error="Username hiyo tayari ipo.",
            form_data=form_data
        )

    db.execute(
        """
        INSERT INTO admins
        (
            username,
            full_name,
            email,
            password_hash,
            role,
            role_id,
            is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            username,
            full_name,
            email or None,
            generate_password_hash(password),
            role["name"],
            role["id"]
        )
    )

    db.commit()
    db.close()

    log_action(
        "admin_created",
        f"Administrator {username} created.",
        f"Role: {role_name}"
    )

    return redirect(
        url_for("admins")
    )


@app.route("/admins/<int:id>/activate", methods=["POST"])
@login_required
@permission_required("admins.manage")
def activate_admin(id):
    db = get_db()

    target = db.execute(
        """
        SELECT *
        FROM admins
        WHERE id = ?
        """,
        (id,)
    ).fetchone()

    if not target:
        db.close()

        return render_template(
            "404.html"
        ), 404

    db.execute(
        """
        UPDATE admins
        SET is_active = 1
        WHERE id = ?
        """,
        (id,)
    )

    db.commit()
    db.close()

    log_action(
        "admin_activated",
        f"Administrator {target['username']} activated.",
        f"Admin ID: {id}"
    )

    return redirect(
        url_for("admins")
    )


@app.route("/admins/<int:id>/deactivate", methods=["POST"])
@login_required
@permission_required("admins.manage")
def deactivate_admin(id):
    current_admin = get_current_admin()

    if current_admin and current_admin["id"] == id:
        return redirect(
            url_for("admins")
        )

    db = get_db()

    target = db.execute(
        """
        SELECT *
        FROM admins
        WHERE id = ?
        """,
        (id,)
    ).fetchone()

    if not target:
        db.close()

        return render_template(
            "404.html"
        ), 404

    db.execute(
        """
        UPDATE admins
        SET is_active = 0
        WHERE id = ?
        """,
        (id,)
    )

    db.commit()
    db.close()

    log_action(
        "admin_deactivated",
        f"Administrator {target['username']} deactivated.",
        f"Admin ID: {id}"
    )

    return redirect(
        url_for("admins")
    )


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template(
            "change_password.html",
            error=None
        )

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

    if not check_password_hash(
        admin["password_hash"],
        current_password
    ):
        return render_template(
            "change_password.html",
            error="Password ya sasa si sahihi."
        )

    if len(new_password) < 8:
        return render_template(
            "change_password.html",
            error="Password mpya lazima iwe na angalau characters 8."
        )

    if new_password != confirm_password:
        return render_template(
            "change_password.html",
            error="Password mpya hazifanani."
        )

    db = get_db()

    db.execute(
        """
        UPDATE admins
        SET password_hash = ?
        WHERE id = ?
        """,
        (
            generate_password_hash(new_password),
            admin["id"]
        )
    )

    db.commit()
    db.close()

    log_action(
        "password_changed",
        "Administrator changed their password."
    )

    return redirect(
        url_for("dashboard")
    )


@app.route("/audit-logs")
@login_required
@permission_required("audit.view")
def audit_logs():
    db = get_db()

    logs = db.execute(
        """
        SELECT
            audit_logs.*,
            admins.username,
            admins.full_name
        FROM audit_logs
        LEFT JOIN admins
            ON audit_logs.admin_id = admins.id
        ORDER BY audit_logs.id DESC
        LIMIT 200
        """
    ).fetchall()

    db.close()

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
    init_database()

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )