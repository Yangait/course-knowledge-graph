"""实体链接人工调试入口。"""

import json

from entity_linker import link_entity
from neo4j_client import driver


def main():
    entity_name = input("请输入实体名称：").strip()

    if not entity_name:
        print("实体名称不能为空。")
        return

    try:
        result = link_entity(entity_name)

        print("\n实体链接结果：")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        driver.close()


if __name__ == "__main__":
    main()
