import time
import ngrok
from dotenv import load_dotenv
load_dotenv()

def start_tunnel() -> None:
    try:
        listener = ngrok.forward( "localhost:8000", authtoken_from_env=True )
        public_url = listener.url()
        print("\nNgrok tunnel started successfully.")
        print(f"Public base URL: {public_url}")
        print(f"Datadog webhook URL: {public_url}/webhook/alert")
        print(f"Jira webhook URL:{public_url}/webhook/jira")
        print("\nPress Ctrl+C to stop the tunnel.")

        while True:
            time.sleep(1)

    except Exception as error:
        print(f"\nFailed to start ngrok tunnel: {error}")


if __name__ == "__main__":
    start_tunnel()