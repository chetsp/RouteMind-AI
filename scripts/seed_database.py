from app.database import Database
from app.seed import seed

if __name__ == "__main__":
    db = Database()
    seed(db)
    hs, cs, services = db.network()
    print(f"Synthetic network: {len(hs)} hubs, {len(cs)} carriers, {len(services)} services")
