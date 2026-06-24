import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

# Configurações do SQLite
SQLITE_DB = "database.db"

def migrate():
    # 1. Obter a URL de conexão do PostgreSQL
    print("--- MIGRADO DE SQLITE PARA POSTGRESQL ---")
    pg_url = os.environ.get("DATABASE_URL")
    
    if not pg_url:
        print("A variável de ambiente DATABASE_URL não está configurada.")
        pg_url = input("Por favor, insira a URL de conexão EXTERNA do seu PostgreSQL no Render:\n> ").strip()
    
    if not pg_url:
        print("Erro: URL do PostgreSQL não fornecida. Abortando.")
        return

    # Substitui postgres:// por postgresql:// se necessário
    pg_url = pg_url.replace("postgres://", "postgresql://", 1)

    if not os.path.exists(SQLITE_DB):
        print(f"Erro: Arquivo local '{SQLITE_DB}' não encontrado. Certifique-se de executar este script na raiz do projeto.")
        return

    print(f"\nConectando ao banco de dados SQLite local ({SQLITE_DB})...")
    conn_lite = sqlite3.connect(SQLITE_DB)
    conn_lite.row_factory = sqlite3.Row
    cur_lite = conn_lite.cursor()

    print("Conectando ao banco de dados PostgreSQL remoto...")
    try:
        conn_pg = psycopg2.connect(pg_url)
        cur_pg = conn_pg.cursor()
    except Exception as e:
        print(f"Erro ao conectar ao PostgreSQL: {e}")
        conn_lite.close()
        return

    try:
        # 2. Criar tabelas no PostgreSQL se elas não existirem
        print("Verificando/Criando tabelas no PostgreSQL...")
        
        cur_pg.execute('''
            CREATE TABLE IF NOT EXISTS clientes (
                id          SERIAL PRIMARY KEY,
                nome        TEXT   NOT NULL,
                telefone    TEXT,
                email       TEXT,
                endereco    TEXT,
                observacoes TEXT
            )
        ''')

        cur_pg.execute('''
            CREATE TABLE IF NOT EXISTS prestadoras (
                id                  SERIAL PRIMARY KEY,
                nome                TEXT   NOT NULL,
                telefone            TEXT,
                especialidades      TEXT,
                disponibilidade     TEXT,
                bairro              TEXT,
                referencias         TEXT,
                preferencia_horario TEXT
            )
        ''')

        cur_pg.execute('''
            CREATE TABLE IF NOT EXISTS agendamentos (
                id               SERIAL  PRIMARY KEY,
                id_cliente       INTEGER NOT NULL REFERENCES clientes(id),
                id_prestadora    INTEGER REFERENCES prestadoras(id),
                data             TEXT    NOT NULL,
                horario          TEXT    NOT NULL,
                status           TEXT    DEFAULT 'Pendente',
                servico_agendado TEXT,
                observacoes      TEXT
            )
        ''')
        conn_pg.commit()
        print("Tabelas prontas no PostgreSQL.")

        # 3. Migrar Clientes
        print("\nMigrando tabela 'clientes'...")
        cur_lite.execute("SELECT * FROM clientes")
        clientes = cur_lite.fetchall()
        for c in clientes:
            cur_pg.execute(
                "INSERT INTO clientes (id, nome, telefone, email, endereco, observacoes) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (c['id'], c['nome'], c['telefone'], c['email'], c['endereco'], c['observacoes'])
            )
        print(f"-> {len(clientes)} clientes processados.")

        # 4. Migrar Prestadoras
        print("\nMigrando tabela 'prestadoras'...")
        cur_lite.execute("SELECT * FROM prestadoras")
        prestadoras = cur_lite.fetchall()
        for p in prestadoras:
            cur_pg.execute(
                "INSERT INTO prestadoras (id, nome, telefone, especialidades, disponibilidade, bairro, referencias, preferencia_horario) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (p['id'], p['nome'], p['telefone'], p['especialidades'], p['disponibilidade'], p['bairro'], p['referencias'], p['preferencia_horario'])
            )
        print(f"-> {len(prestadoras)} prestadoras processadas.")

        # 5. Migrar Agendamentos
        print("\nMigrando tabela 'agendamentos'...")
        cur_lite.execute("SELECT * FROM agendamentos")
        agendamentos = cur_lite.fetchall()
        for a in agendamentos:
            cur_pg.execute(
                "INSERT INTO agendamentos (id, id_cliente, id_prestadora, data, horario, status, servico_agendado, observacoes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (a['id'], a['id_cliente'], a['id_prestadora'], a['data'], a['horario'], a['status'], a['servico_agendado'], a['observacoes'])
            )
        print(f"-> {len(agendamentos)} agendamentos processados.")

        # 6. Atualizar sequências de ID no PostgreSQL (essencial para evitar erros em novos registros)
        print("\nAtualizando sequências de IDs no PostgreSQL...")
        cur_pg.execute("SELECT setval(pg_get_serial_sequence('clientes', 'id'), COALESCE(MAX(id), 1)) FROM clientes;")
        cur_pg.execute("SELECT setval(pg_get_serial_sequence('prestadoras', 'id'), COALESCE(MAX(id), 1)) FROM prestadoras;")
        cur_pg.execute("SELECT setval(pg_get_serial_sequence('agendamentos', 'id'), COALESCE(MAX(id), 1)) FROM agendamentos;")
        
        conn_pg.commit()
        print("Migração concluída com sucesso e sequências de IDs sincronizadas!")

    except Exception as e:
        conn_pg.rollback()
        print(f"\nErro durante a migração: {e}")
    finally:
        conn_lite.close()
        conn_pg.close()

if __name__ == "__main__":
    migrate()
