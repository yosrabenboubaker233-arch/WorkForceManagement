"""
Supprime les doublons de pointage (même employé + même date) avant
d'appliquer la migration qui ajoute la contrainte d'unicité.

Pour chaque doublon, on garde la fiche la "plus complète" (celle qui a un
check_in renseigné en priorité, sinon la plus ancienne par id) et on
supprime les autres.

Usage :
    python nettoyer_doublons_pointage.py

(à lancer depuis le dossier WorkForce, à côté de db.sqlite3)
"""
import sqlite3

conn = sqlite3.connect("db.sqlite3")
cur = conn.cursor()

cur.execute("""
    SELECT employee_id, date, COUNT(*) as c
    FROM attendance_attendance
    GROUP BY employee_id, date
    HAVING c > 1
""")
duplicates = cur.fetchall()

if not duplicates:
    print("Aucun doublon trouvé. Rien à faire.")
else:
    print(f"{len(duplicates)} doublon(s) trouvé(s) :")
    total_deleted = 0
    for employee_id, d, count in duplicates:
        cur.execute("""
            SELECT id, check_in FROM attendance_attendance
            WHERE employee_id=? AND date=?
            ORDER BY (check_in IS NULL), id
        """, (employee_id, d))
        rows = cur.fetchall()
        keep_id = rows[0][0]
        delete_ids = [r[0] for r in rows[1:]]
        print(f"  employé {employee_id}, {d} : garde id={keep_id}, supprime {delete_ids}")
        cur.executemany("DELETE FROM attendance_attendance WHERE id=?", [(i,) for i in delete_ids])
        total_deleted += len(delete_ids)
    conn.commit()
    print(f"\n{total_deleted} fiche(s) en double supprimée(s).")

conn.close()
