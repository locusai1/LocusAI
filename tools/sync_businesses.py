import os, json, csv, shutil, uuid, sqlite3, re
DB="receptionist.db"

def slugify(s):
    s=(s or "").lower().strip()
    s=re.sub(r"[^a-z0-9]+","-",s)
    return s.strip("-")

def main():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    cur=con.cursor()
    rows=cur.execute("SELECT * FROM businesses").fetchall()
    os.makedirs("businesses", exist_ok=True)
    os.makedirs("static/tenants", exist_ok=True)
    moved=0; fixed=0
    for b in rows:
        bid=b["id"]; name=b["name"]; slug=b["slug"]; logo=b["logo_path"]
        # slug hygiene
        clean=slugify(slug or name)
        if clean != slug:
            cur.execute("UPDATE businesses SET slug=? WHERE id=?", (clean, bid))
            slug=clean; fixed+=1
        # tenant key
        if not b["tenant_key"]:
            cur.execute("UPDATE businesses SET tenant_key=? WHERE id=?", (str(uuid.uuid4()), bid))
        # paths
        data_dir   = os.path.join("businesses", slug)
        static_dir = os.path.join("static","tenants", slug)
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(static_dir, exist_ok=True)
        # move logo from uploads -> tenants/<slug>/
        if logo and (logo.startswith("uploads/") or logo.startswith("static/uploads/")):
            src = logo if logo.startswith("static/") else os.path.join("static", logo)
            if os.path.exists(src):
                ext = os.path.splitext(src)[1].lower() or ".png"
                dest_rel = f"tenants/{slug}/logo{ext}"
                dest_abs = os.path.join("static", dest_rel)
                try:
                    shutil.copy2(src, dest_abs)
                    cur.execute("UPDATE businesses SET logo_path=? WHERE id=?", (dest_rel, bid))
                    moved+=1
                except Exception:
                    pass
        # write meta.json
        meta = {
            "id": bid, "tenant_key": b["tenant_key"], "name": name, "slug": slug,
            "hours": b["hours"], "address": b["address"], "tone": b["tone"],
            "accent_color": b["accent_color"], "logo_path": (cur.execute("SELECT logo_path FROM businesses WHERE id=?", (bid,)).fetchone()["logo_path"]),
            "created_at": b["created_at"]
        }
        with open(os.path.join(data_dir,"meta.json"), "w") as f: json.dump(meta, f, indent=2)
        # export services.csv
        svc = cur.execute("SELECT name,duration_min,price,active,external_id FROM services WHERE business_id=? ORDER BY name", (bid,)).fetchall()
        with open(os.path.join(data_dir,"services.csv"), "w", newline="") as f:
            w=csv.writer(f); w.writerow(["name","duration_min","price","active","external_id"])
            for r in svc: w.writerow([r["name"], r["duration_min"], r["price"] or "", r["active"], r["external_id"] or ""])
        # export integrations.json
        integ = cur.execute("SELECT provider_key,status,account_json FROM integrations WHERE business_id=?", (bid,)).fetchall()
        export = [{"provider_key":i["provider_key"],"status":i["status"],"account":(json.loads(i["account_json"]) if i["account_json"] else {})} for i in integ]
        with open(os.path.join(data_dir,"integrations.json"), "w") as f: json.dump(export, f, indent=2)
        # remember paths on business
        cur.execute("UPDATE businesses SET files_path=?, static_path=? WHERE id=?", (f"businesses/{slug}", f"tenants/{slug}", bid))
    con.commit()
    print(f"Done. Slugs fixed: {fixed}, logos moved: {moved}, businesses: {len(rows)}")
if __name__=="__main__": main()
