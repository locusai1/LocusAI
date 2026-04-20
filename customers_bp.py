# customers_bp.py — Customer relationship management
# Production-grade with full CRUD, search, and customer insights

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from core.db import get_conn, list_businesses, transaction
from core.authz import user_can_access_business
from core.validators import (
    safe_int, validate_email, validate_phone, validate_name
)

logger = logging.getLogger(__name__)

bp = Blueprint("customers", __name__)


# ============================================================================
# Authentication & Authorization Helpers
# ============================================================================

def _user() -> Optional[dict]:
    """Get the current user from session."""
    return session.get("user")


def _need_login() -> bool:
    """Check if login is required."""
    return _user() is None


def _can_access(bid: int) -> bool:
    """Check if current user can access the given business."""
    return user_can_access_business(_user(), bid)


# ============================================================================
# Customer Database Operations
# ============================================================================

def get_customer_by_id(customer_id: int) -> Optional[Dict[str, Any]]:
    """Get a customer by ID."""
    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM customers WHERE id = ?",
            (customer_id,)
        ).fetchone()
        return dict(row) if row else None


def get_customer_by_email(business_id: int, email: str) -> Optional[Dict[str, Any]]:
    """Get a customer by email for a business."""
    if not email:
        return None
    with get_conn() as con:
        row = con.execute(
            "SELECT * FROM customers WHERE business_id = ? AND email = ? COLLATE NOCASE",
            (business_id, email.strip().lower())
        ).fetchone()
        return dict(row) if row else None


def get_customer_by_phone(business_id: int, phone: str) -> Optional[Dict[str, Any]]:
    """Get a customer by phone for a business."""
    if not phone:
        return None
    # Normalize phone: remove non-digits for comparison
    normalized = ''.join(c for c in phone if c.isdigit())
    if len(normalized) < 7:
        return None

    with get_conn() as con:
        # Search for phone containing the digits
        rows = con.execute(
            "SELECT * FROM customers WHERE business_id = ? AND phone IS NOT NULL",
            (business_id,)
        ).fetchall()

        for row in rows:
            row_phone = ''.join(c for c in (row["phone"] or "") if c.isdigit())
            if row_phone and (normalized in row_phone or row_phone in normalized or normalized[-10:] == row_phone[-10:]):
                return dict(row)

        return None


def find_or_create_customer(
    business_id: int,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    source: str = "booking"
) -> Optional[int]:
    """Find existing customer by email/phone or create new one. Returns customer ID."""

    # Try to find by email first
    if email:
        customer = get_customer_by_email(business_id, email)
        if customer:
            # Update name if we have a better one
            if name and (not customer.get("name") or customer.get("name") == "Unknown"):
                update_customer(customer["id"], name=name)
            # Update phone if we have one and they don't
            if phone and not customer.get("phone"):
                update_customer(customer["id"], phone=phone)
            # Update last seen
            _touch_customer(customer["id"])
            return customer["id"]

    # Try to find by phone
    if phone:
        customer = get_customer_by_phone(business_id, phone)
        if customer:
            # Update name if we have a better one
            if name and (not customer.get("name") or customer.get("name") == "Unknown"):
                update_customer(customer["id"], name=name)
            # Update email if we have one and they don't
            if email and not customer.get("email"):
                update_customer(customer["id"], email=email)
            # Update last seen
            _touch_customer(customer["id"])
            return customer["id"]

    # Create new customer
    return create_customer(
        business_id=business_id,
        name=name or "Unknown",
        email=email,
        phone=phone,
        notes=f"Auto-created from {source}"
    )


def create_customer(
    business_id: int,
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    notes: Optional[str] = None,
    tags: Optional[str] = None
) -> Optional[int]:
    """Create a new customer. Returns customer ID or None on failure."""
    try:
        with transaction() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO customers (
                    business_id, name, email, phone, notes, tags,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """, (
                business_id,
                name or "Unknown",
                email.strip().lower() if email else None,
                phone.strip() if phone else None,
                notes,
                tags
            ))
            customer_id = cur.lastrowid
            logger.info(f"Created customer {customer_id} for business {business_id}")
            return customer_id
    except Exception as e:
        logger.error(f"Failed to create customer: {e}")
        return None


def update_customer(customer_id: int, **fields) -> bool:
    """Update customer fields. Returns True if successful."""
    allowed = {"name", "email", "phone", "notes", "tags"}
    safe_fields = {k: v for k, v in fields.items() if k in allowed and v is not None}

    if not safe_fields:
        return False

    # Normalize email
    if "email" in safe_fields and safe_fields["email"]:
        safe_fields["email"] = safe_fields["email"].strip().lower()

    cols = [f"{k} = ?" for k in safe_fields.keys()]
    vals = list(safe_fields.values())
    vals.append(customer_id)

    try:
        with transaction() as con:
            con.execute(
                f"UPDATE customers SET {', '.join(cols)}, updated_at = datetime('now') WHERE id = ?",
                tuple(vals)
            )
        return True
    except Exception as e:
        logger.error(f"Failed to update customer {customer_id}: {e}")
        return False


def _touch_customer(customer_id: int) -> None:
    """Update last_seen_at for a customer."""
    try:
        with get_conn() as con:
            con.execute(
                "UPDATE customers SET last_seen_at = datetime('now') WHERE id = ?",
                (customer_id,)
            )
            con.commit()
    except Exception as e:
        logger.warning(f"Failed to touch customer {customer_id}: {e}")


def delete_customer(customer_id: int) -> bool:
    """Delete a customer. Returns True if successful."""
    try:
        with transaction() as con:
            # First unlink appointments and sessions
            con.execute("UPDATE appointments SET customer_id = NULL WHERE customer_id = ?", (customer_id,))
            con.execute("UPDATE sessions SET customer_id = NULL WHERE customer_id = ?", (customer_id,))
            # Then delete customer
            con.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        logger.info(f"Deleted customer {customer_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete customer {customer_id}: {e}")
        return False


def search_customers(
    business_id: int,
    query: str = "",
    limit: int = 50,
    offset: int = 0
) -> Tuple[List[Dict], int]:
    """Search customers by name, email, or phone. Returns (results, total_count)."""
    with get_conn() as con:
        base_query = "FROM customers WHERE business_id = ?"
        params = [business_id]

        if query:
            query = query.strip()
            base_query += """ AND (
                name LIKE ? COLLATE NOCASE OR
                email LIKE ? COLLATE NOCASE OR
                phone LIKE ? OR
                tags LIKE ? COLLATE NOCASE
            )"""
            like_query = f"%{query}%"
            params.extend([like_query, like_query, like_query, like_query])

        # Get total count
        count_row = con.execute(f"SELECT COUNT(*) as cnt {base_query}", params).fetchone()
        total = count_row["cnt"] if count_row else 0

        # Get results
        rows = con.execute(
            f"""SELECT * {base_query}
                ORDER BY last_seen_at DESC, name ASC
                LIMIT ? OFFSET ?""",
            params + [limit, offset]
        ).fetchall()

        return [dict(r) for r in rows], total


def get_customer_stats(customer_id: int) -> Dict[str, Any]:
    """Get statistics for a customer."""
    with get_conn() as con:
        # Appointment counts
        appt_row = con.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) as confirmed
            FROM appointments WHERE customer_id = ?
        """, (customer_id,)).fetchone()

        # Session count
        session_row = con.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE customer_id = ?",
            (customer_id,)
        ).fetchone()

        # Last appointment
        last_appt = con.execute("""
            SELECT start_at, service, status FROM appointments
            WHERE customer_id = ?
            ORDER BY start_at DESC LIMIT 1
        """, (customer_id,)).fetchone()

        return {
            "total_appointments": appt_row["total"] if appt_row else 0,
            "completed_appointments": appt_row["completed"] if appt_row else 0,
            "cancelled_appointments": appt_row["cancelled"] if appt_row else 0,
            "pending_appointments": appt_row["pending"] if appt_row else 0,
            "confirmed_appointments": appt_row["confirmed"] if appt_row else 0,
            "total_sessions": session_row["cnt"] if session_row else 0,
            "last_appointment": dict(last_appt) if last_appt else None,
        }


def get_customer_appointments(customer_id: int, limit: int = 20) -> List[Dict]:
    """Get appointments for a customer."""
    with get_conn() as con:
        rows = con.execute("""
            SELECT * FROM appointments
            WHERE customer_id = ?
            ORDER BY COALESCE(start_at, created_at) DESC
            LIMIT ?
        """, (customer_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_customer_sessions(customer_id: int, limit: int = 10) -> List[Dict]:
    """Get chat sessions for a customer with message counts."""
    with get_conn() as con:
        rows = con.execute("""
            SELECT s.*,
                   (SELECT COUNT(*) FROM messages WHERE session_id = s.id) as message_count,
                   (SELECT text FROM messages WHERE session_id = s.id ORDER BY id DESC LIMIT 1) as last_message
            FROM sessions s
            WHERE s.customer_id = ?
            ORDER BY s.created_at DESC
            LIMIT ?
        """, (customer_id, limit)).fetchall()
        return [dict(r) for r in rows]


def merge_customers(primary_id: int, secondary_id: int) -> bool:
    """Merge two customer records, keeping the primary and deleting secondary."""
    try:
        with transaction() as con:
            # Get both customers
            primary = con.execute("SELECT * FROM customers WHERE id = ?", (primary_id,)).fetchone()
            secondary = con.execute("SELECT * FROM customers WHERE id = ?", (secondary_id,)).fetchone()

            if not primary or not secondary:
                return False

            if primary["business_id"] != secondary["business_id"]:
                return False

            # Update primary with any missing info from secondary
            updates = []
            params = []

            if not primary["email"] and secondary["email"]:
                updates.append("email = ?")
                params.append(secondary["email"])
            if not primary["phone"] and secondary["phone"]:
                updates.append("phone = ?")
                params.append(secondary["phone"])
            if (not primary["name"] or primary["name"] == "Unknown") and secondary["name"] and secondary["name"] != "Unknown":
                updates.append("name = ?")
                params.append(secondary["name"])

            # Merge notes
            if secondary["notes"]:
                new_notes = f"{primary['notes'] or ''}\n---\nMerged from customer #{secondary_id}:\n{secondary['notes']}".strip()
                updates.append("notes = ?")
                params.append(new_notes)

            # Merge tags
            if secondary["tags"]:
                primary_tags = set((primary["tags"] or "").split(","))
                secondary_tags = set((secondary["tags"] or "").split(","))
                merged_tags = ",".join(filter(None, primary_tags | secondary_tags))
                updates.append("tags = ?")
                params.append(merged_tags)

            if updates:
                params.append(primary_id)
                con.execute(f"UPDATE customers SET {', '.join(updates)}, updated_at = datetime('now') WHERE id = ?", params)

            # Move appointments
            con.execute("UPDATE appointments SET customer_id = ? WHERE customer_id = ?", (primary_id, secondary_id))

            # Move sessions
            con.execute("UPDATE sessions SET customer_id = ? WHERE customer_id = ?", (primary_id, secondary_id))

            # Delete secondary
            con.execute("DELETE FROM customers WHERE id = ?", (secondary_id,))

            logger.info(f"Merged customer {secondary_id} into {primary_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to merge customers {primary_id} and {secondary_id}: {e}")
        return False


# ============================================================================
# Routes - Customer List
# ============================================================================

@bp.route("/customers")
def customers_index():
    """List customers with search."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.args.get("business_id"))
    query = request.args.get("q", "").strip()
    page = safe_int(request.args.get("page"), default=1, min_val=1)
    per_page = 25

    businesses = list_businesses(limit=500)
    customers = []
    total = 0

    if bid:
        if not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("customers.customers_index"))

        customers, total = search_customers(
            business_id=bid,
            query=query,
            limit=per_page,
            offset=(page - 1) * per_page
        )

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return render_template(
        "customers.html",
        businesses=businesses,
        business_id=bid,
        customers=customers,
        query=query,
        page=page,
        total_pages=total_pages,
        total=total
    )


# ============================================================================
# Routes - Customer Detail
# ============================================================================

@bp.route("/customers/<int:customer_id>")
def customer_detail(customer_id: int):
    """View customer details."""
    if _need_login():
        return redirect(url_for("auth.login"))

    customer = get_customer_by_id(customer_id)
    if not customer:
        flash("Customer not found.", "err")
        return redirect(url_for("customers.customers_index"))

    if not _can_access(customer["business_id"]):
        flash("Access denied.", "err")
        return redirect(url_for("customers.customers_index"))

    stats = get_customer_stats(customer_id)
    appointments = get_customer_appointments(customer_id, limit=20)
    sessions = get_customer_sessions(customer_id, limit=10)

    # Fetch voice call history by matching phone number
    voice_calls = []
    if customer.get("phone"):
        try:
            from core.db import get_conn as _get_conn
            phone_digits = ''.join(c for c in customer["phone"] if c.isdigit())
            last_10 = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
            with _get_conn() as con:
                rows = con.execute("""
                    SELECT retell_call_id, direction, started_at, duration_seconds,
                           call_intent, call_outcome, call_summary, sentiment, recording_url
                    FROM voice_calls
                    WHERE business_id = ? AND from_number LIKE ?
                    ORDER BY started_at DESC LIMIT 10
                """, (customer["business_id"], f"%{last_10}%")).fetchall()
                voice_calls = [dict(r) for r in rows]
        except Exception:
            pass

    return render_template(
        "customer_detail.html",
        customer=customer,
        stats=stats,
        appointments=appointments,
        sessions=sessions,
        voice_calls=voice_calls,
    )


# ============================================================================
# Routes - Create Customer
# ============================================================================

@bp.route("/customers/new", methods=["GET", "POST"])
def customer_new():
    """Create a new customer."""
    if _need_login():
        return redirect(url_for("auth.login"))

    bid = safe_int(request.args.get("business_id") or request.form.get("business_id"))

    if request.method == "POST":
        if not bid or not _can_access(bid):
            flash("Access denied.", "err")
            return redirect(url_for("customers.customers_index"))

        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        tags = (request.form.get("tags") or "").strip()

        # Validation
        errors = []

        if name:
            name_valid, name_result = validate_name(name, "Name", min_length=1, max_length=100)
            if not name_valid:
                errors.append(name_result)
            else:
                name = name_result

        if email:
            email_valid, email_result = validate_email(email)
            if not email_valid:
                errors.append(f"Email: {email_result}")
            else:
                email = email_result

        if phone:
            phone_valid, phone_result = validate_phone(phone)
            if not phone_valid:
                errors.append(f"Phone: {phone_result}")
            else:
                phone = phone_result

        if not name and not email and not phone:
            errors.append("At least one of name, email, or phone is required.")

        if errors:
            for err in errors:
                flash(err, "err")
            return redirect(url_for("customers.customer_new", business_id=bid))

        # Check for duplicates
        if email:
            existing = get_customer_by_email(bid, email)
            if existing:
                flash(f"A customer with this email already exists.", "err")
                return redirect(url_for("customers.customer_detail", customer_id=existing["id"]))

        if phone:
            existing = get_customer_by_phone(bid, phone)
            if existing:
                flash(f"A customer with this phone already exists.", "err")
                return redirect(url_for("customers.customer_detail", customer_id=existing["id"]))

        customer_id = create_customer(
            business_id=bid,
            name=name or "Unknown",
            email=email or None,
            phone=phone or None,
            notes=notes or None,
            tags=tags or None
        )

        if customer_id:
            flash("Customer created successfully.", "ok")
            return redirect(url_for("customers.customer_detail", customer_id=customer_id))
        else:
            flash("Failed to create customer.", "err")
            return redirect(url_for("customers.customer_new", business_id=bid))

    businesses = list_businesses(limit=500)
    return render_template("customer_new.html", businesses=businesses, business_id=bid)


# ============================================================================
# Routes - Edit Customer
# ============================================================================

@bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
def customer_edit(customer_id: int):
    """Edit a customer."""
    if _need_login():
        return redirect(url_for("auth.login"))

    customer = get_customer_by_id(customer_id)
    if not customer:
        flash("Customer not found.", "err")
        return redirect(url_for("customers.customers_index"))

    if not _can_access(customer["business_id"]):
        flash("Access denied.", "err")
        return redirect(url_for("customers.customers_index"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        tags = (request.form.get("tags") or "").strip()

        # Validation
        errors = []

        if name:
            name_valid, name_result = validate_name(name, "Name", min_length=1, max_length=100)
            if not name_valid:
                errors.append(name_result)
            else:
                name = name_result

        if email:
            email_valid, email_result = validate_email(email)
            if not email_valid:
                errors.append(f"Email: {email_result}")
            else:
                email = email_result
                # Check for duplicates (excluding self)
                existing = get_customer_by_email(customer["business_id"], email)
                if existing and existing["id"] != customer_id:
                    errors.append("Another customer with this email already exists.")

        if phone:
            phone_valid, phone_result = validate_phone(phone)
            if not phone_valid:
                errors.append(f"Phone: {phone_result}")
            else:
                phone = phone_result

        if errors:
            for err in errors:
                flash(err, "err")
            return redirect(url_for("customers.customer_edit", customer_id=customer_id))

        update_customer(
            customer_id,
            name=name or None,
            email=email or None,
            phone=phone or None,
            notes=notes,
            tags=tags
        )

        flash("Customer updated.", "ok")
        return redirect(url_for("customers.customer_detail", customer_id=customer_id))

    return render_template("customer_edit.html", customer=customer)


# ============================================================================
# Routes - Delete Customer
# ============================================================================

@bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
def customer_delete(customer_id: int):
    """Delete a customer."""
    if _need_login():
        return redirect(url_for("auth.login"))

    customer = get_customer_by_id(customer_id)
    if not customer:
        flash("Customer not found.", "err")
        return redirect(url_for("customers.customers_index"))

    bid = customer["business_id"]
    if not _can_access(bid):
        flash("Access denied.", "err")
        return redirect(url_for("customers.customers_index"))

    if delete_customer(customer_id):
        flash("Customer deleted.", "ok")
    else:
        flash("Failed to delete customer.", "err")

    return redirect(url_for("customers.customers_index", business_id=bid))


# ============================================================================
# Routes - Merge Customers
# ============================================================================

@bp.route("/customers/<int:customer_id>/merge", methods=["POST"])
def customer_merge(customer_id: int):
    """Merge another customer into this one."""
    if _need_login():
        return redirect(url_for("auth.login"))

    customer = get_customer_by_id(customer_id)
    if not customer:
        flash("Customer not found.", "err")
        return redirect(url_for("customers.customers_index"))

    if not _can_access(customer["business_id"]):
        flash("Access denied.", "err")
        return redirect(url_for("customers.customers_index"))

    secondary_id = safe_int(request.form.get("merge_with"))
    if not secondary_id or secondary_id == customer_id:
        flash("Invalid customer to merge.", "err")
        return redirect(url_for("customers.customer_detail", customer_id=customer_id))

    secondary = get_customer_by_id(secondary_id)
    if not secondary or secondary["business_id"] != customer["business_id"]:
        flash("Cannot merge customers from different businesses.", "err")
        return redirect(url_for("customers.customer_detail", customer_id=customer_id))

    if merge_customers(customer_id, secondary_id):
        flash(f"Successfully merged customer records.", "ok")
    else:
        flash("Failed to merge customers.", "err")

    return redirect(url_for("customers.customer_detail", customer_id=customer_id))


# ============================================================================
# API Routes (for AJAX)
# ============================================================================

@bp.route("/api/customers/search")
def api_customer_search():
    """API endpoint for customer search (autocomplete)."""
    if _need_login():
        return jsonify({"error": "Unauthorized"}), 401

    bid = safe_int(request.args.get("business_id"))
    query = request.args.get("q", "").strip()

    if not bid or not _can_access(bid):
        return jsonify({"error": "Access denied"}), 403

    customers, _ = search_customers(business_id=bid, query=query, limit=10)

    return jsonify({
        "customers": [
            {
                "id": c["id"],
                "name": c["name"],
                "email": c["email"],
                "phone": c["phone"]
            }
            for c in customers
        ]
    })
