from app import create_app

app = create_app()
application = app

if __name__ == "__main__":
    host = app.config.get("HOST", "0.0.0.0")
    port = app.config.get("PORT", 5000)
    debug = app.config.get("DEBUG", False)

    print(f"\n==========================================")
    print(f"  T2T DRIVE Backend - Foundation Phase 1  ")
    print(f"  Listening on http://{host}:{port}        ")
    print(f"  Environment: {app.config.get('ENV')}    ")
    print(f"==========================================\n")

    app.run(host=host, port=port, debug=debug)
