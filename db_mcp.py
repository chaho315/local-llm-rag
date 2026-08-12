"""읽기전용 DB MCP 서버 (Oracle + MySQL).

MCP 클라이언트(Claude Desktop 등)에서 아래 도구를 사용할 수 있게 노출한다.
모든 도구는 config.yaml 의 테이블 허용목록 + 읽기전용 규칙을 강제한다.

도구:
  list_allowed_tables(db)              : 조회 가능한 테이블 목록
  describe_table(db, table)            : 컬럼 구조
  query(db, table, columns, where, limit) : 허용 테이블 단일 SELECT

실행:  python db_mcp.py     (stdio 전송)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app import db as dbmod

mcp = FastMCP("company-db")


@mcp.tool()
def list_allowed_tables(db: str) -> list[str]:
    """조회 가능한(허용된) 테이블 목록. db 는 'oracle' 또는 'mysql'."""
    return sorted(dbmod._allowed_tables(db))


@mcp.tool()
def describe_table(db: str, table: str) -> list[dict]:
    """허용된 테이블의 컬럼 구조(이름/타입)를 반환."""
    dbmod.assert_table_allowed(db, table)
    if db == "oracle":
        sql = ("SELECT column_name, data_type FROM user_tab_columns "
               "WHERE table_name = :1 ORDER BY column_id")
        return dbmod.run_select("oracle", sql, [table.upper()])
    sql = ("SELECT column_name, data_type FROM information_schema.columns "
           "WHERE table_name = %s ORDER BY ordinal_position")
    return dbmod.run_select("mysql", sql, (table,))


@mcp.tool()
def query(db: str, table: str, columns: str = "*", where: str = "", limit: int = 50) -> list[dict]:
    """허용된 단일 테이블에서 읽기전용 SELECT.

    임의 SQL 대신 테이블/컬럼/조건을 나눠 받아 안전하게 조립한다.
    columns, where 에는 union/select/;/-- 등 주입 토큰이 금지된다.
    """
    dbmod.assert_table_allowed(db, table)
    dbmod.assert_safe_fragment(columns)
    dbmod.assert_safe_fragment(where)
    limit = max(1, min(int(limit), 500))
    where_sql = f" WHERE {where}" if where else ""
    sql = f"SELECT {columns} FROM {table}{where_sql}"
    return dbmod.run_select(db, sql, limit=limit)


if __name__ == "__main__":
    mcp.run()
