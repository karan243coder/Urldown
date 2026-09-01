# BIMBO v4.0
from config import Config
from database.database import Database

bimbo = Database(Config.BIMBO_DATABASE_URL, Config.BIMBO_SESSION_NAME)
