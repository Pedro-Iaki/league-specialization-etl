from loguru import logger

import extract.init_extraction_db as init_db


def reset_local_data():
    init_db.clear_raw_and_compacted_data()
    logger.info("Extraction state reset after successful load.")


if __name__ == "__main__":
    reset_local_data()
