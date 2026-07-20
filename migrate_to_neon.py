import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

def migrate():
    print("=" * 60)
    print("   MIGRAÇÃO DE BANCO DE DADOS POSTGRESQL PARA O NEON")
    print("=" * 60)
    
    # 1. Obter URLs dos bancos
    source_url = os.environ.get("SOURCE_DATABASE_URL")
    dest_url = os.environ.get("DATABASE_URL") # Neon DB URL
    
    if not source_url:
        print("A variável de ambiente SOURCE_DATABASE_URL não está configurada (ex: Banco do Render).")
        source_url = input("Por favor, insira a URL de conexão externa do banco ORIGEM (Render):\n> ").strip()
        
    if not dest_url:
        print("\nA variável de ambiente DATABASE_URL não está configurada (ex: Banco do Neon).")
        dest_url = input("Por favor, insira a URL de conexão do banco DESTINO (Neon):\n> ").strip()
        
    if not source_url or not dest_url:
        print("\nErro: Ambas as URLs de conexão são necessárias. Abortando.")
        sys.exit(1)
        
    # Ajusta os prefixos postgres:// para postgresql:// se necessário
    source_url = source_url.replace("postgres://", "postgresql://", 1)
    dest_url = dest_url.replace("postgres://", "postgresql://", 1)
    
    print("\nConectando ao banco de dados de ORIGEM (Render)...")
    try:
        conn_src = psycopg2.connect(source_url)
        cur_src = conn_src.cursor(cursor_factory=RealDictCursor)
        print("Conectado à Origem com sucesso!")
    except Exception as e:
        print(f"Erro ao conectar ao banco de origem: {e}")
        return

    print("Conectando ao banco de dados de DESTINO (Neon)...")
    try:
        conn_dest = psycopg2.connect(dest_url)
        cur_dest = conn_dest.cursor()
        print("Conectado ao Destino com sucesso!")
    except Exception as e:
        print(f"Erro ao conectar ao banco de destino: {e}")
        conn_src.close()
        return

    try:
        # 2. Inicializar as tabelas no Neon (se não existirem)
        # Configuramos temporariamente DATABASE_URL no os.environ e importamos/chamamos init_db de app.py
        print("\nInicializando tabelas e migrações no banco de destino (Neon)...")
        os.environ["DATABASE_URL"] = dest_url
        from app import init_db
        init_db()
        print("Tabelas inicializadas com sucesso no Neon!")
        
        # 3. Listar tabelas para migrar
        tables = ['clientes', 'prestadoras', 'agendamentos']
        
        for table in tables:
            print(f"\nMigrando dados da tabela '{table}'...")
            
            # Limpar dados existentes na tabela destino antes de migrar (para evitar conflitos)
            # Como faremos ON CONFLICT (id) DO NOTHING, opcionalmente limpamos ou apenas pulamos.
            # Vamos usar ON CONFLICT (id) DO NOTHING. Se o usuário quiser uma cópia limpa,
            # ele pode limpar o banco Neon antes ou o script faz isso.
            # Vamos apenas rodar o INSERT com ON CONFLICT (id) DO NOTHING.
            
            # Buscar dados da origem
            cur_src.execute(f"SELECT * FROM {table}")
            rows = cur_src.fetchall()
            
            if not rows:
                print(f"-> Nenhuns dados encontrados na tabela '{table}' de origem.")
                continue
                
            # Obter nomes das colunas a partir do primeiro registro
            columns = list(rows[0].keys())
            placeholders = ", ".join(["%s"] * len(columns))
            cols_str = ", ".join(columns)
            
            # Montar query de inserção dinâmica
            insert_query = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING"
            
            # Inserir no destino
            inserted_count = 0
            for r in rows:
                values = tuple(r[col] for col in columns)
                cur_dest.execute(insert_query, values)
                inserted_count += 1
                
            print(f"-> {inserted_count} registros processados para a tabela '{table}'.")
            
        # 4. Sincronizar as sequências no Neon (muito importante para auto-incremento de SERIAL)
        print("\nSincronizando sequências de IDs no banco de destino (Neon)...")
        for table in tables:
            cur_dest.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table};")
            
        conn_dest.commit()
        print("\nMigração de banco de dados concluída com sucesso!")
        
    except Exception as e:
        conn_dest.rollback()
        print(f"\nErro durante a migração: {e}")
    finally:
        cur_src.close()
        conn_src.close()
        cur_dest.close()
        conn_dest.close()

if __name__ == "__main__":
    migrate()
