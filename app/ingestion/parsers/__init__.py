from app.ingestion.parsers.bitrix import BitrixParser
from app.ingestion.parsers.insales import InsalesParser
from app.ingestion.parsers.woocommerce import WooCommerceParser

PARSERS = {
    "gridmir": InsalesParser,
    "darkrain": WooCommerceParser,
    "kutezh": BitrixParser,
}
