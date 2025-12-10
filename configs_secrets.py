import subprocess
import getpass
from typing import List, Dict

def parse_secret_key(secret_full_key: str):
    """
    Parse a secret key like 'github.personal_access_token' 
    Returns (server_prefix, secret_name)
    """
    parts = secret_full_key.split('.', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return secret_full_key, secret_full_key

def set_docker_secret_interactive(server_name:str, secret_key:str):
    """
    Prompt user to enter a secret value and set it via docker CLI
    """
    print(f"\n{'─'*60}")
    print(f"🔑 Secret: {secret_key}")
    print(f"{'─'*60}")

    secret_value = getpass.getpass(f"Enter value for '{secret_key}' (input hidden): ")
    if not secret_value.strip():
        print(f"⚠️  Skipping empty secret '{secret_key}'")
        return False
    
    try:
        result = subprocess.run(
            ['docker', 'mcp', 'secret', 'set', f'{server_name}/{secret_key}'],
            input=secret_value.encode(),
            capture_output=True,
            timeout=30,
            text=False
        )

        if result.returncode == 0:
            print(f"✓ Secret '{secret_key}' set successfully")
            return True
        else:
            error_msg = result.stderr.decode() if result.stderr else "Unknown error"
            print(f"✗ Failed to set secret '{secret_key}': {error_msg}")
            return False
        
    except subprocess.TimeoutExpired:
        print(f"✗ Timeout while setting secret '{secret_key}'")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {str(e)}")
        return False

def prompt_manual_secret_setup(server_name: str, secret_keys: List[str]):
    """
    Show instructions for manual secret setup via CLI
    """
    print(f"\n{'='*70}")
    print("🔐 SECRET CONFIGURATION REQUIRED")
    print(f"{'='*70}")
    print(f"\nServer: {server_name}")
    print("\nRun these commands in your terminal:\n")
    
    for secret_key in secret_keys:
        print(f"  docker mcp secret set {server_name}/{secret_key}")
    
    print(f"\n{'='*70}")

def handle_secrets_interactive(server:Dict):
    """
    Handle secret configuration interactively
    Returns True if secrets were configured successfully
    """

    if 'required_secrets' not in server or not server['required_secrets']:
        return True  # No secrets needed
    
    server_name = server['name']
    required_secrets = server['required_secrets']

    print(f"\n{'='*70}")
    print(f"🔐 Server '{server_name}' requires secret configuration")
    print(f"{'='*70}")
    print(f"\nRequired secrets: {', '.join(required_secrets)}")

    print("\nHow would you like to configure secrets?")
    print("1. Interactive mode (enter values now)")
    print("2. Manual mode (I'll run docker commands myself)")
    print("3. Skip (configure later)")

    choice = input("\nEnter choice (1/2/3): ").strip()

    if choice == '1':
        # Interactive mode
        print("\n--- Interactive Secret Configuration ---")
        success_count = 0
        
        for secret_key in required_secrets:
            success = set_docker_secret_interactive(server_name, secret_key)
            if success:
                success_count += 1
            else:
                print(f"\n⚠️  Required secret '{secret_key}' was not set!")
                retry = input("Retry? (y/n): ").strip().lower()
                if retry == 'y':
                    success = set_docker_secret_interactive(server_name, secret_key)
                    if success:
                        success_count += 1
        
        if success_count == len(required_secrets):
            print(f"\n✓ All {success_count} required secrets configured successfully")
            return True
        else:
            print(f"\n⚠️  Only {success_count}/{len(required_secrets)} secrets were configured")
            proceed = input("Continue anyway? (y/n): ").strip().lower()
            return proceed == 'y'
        
    elif choice == '2':
        # Manual mode
        prompt_manual_secret_setup(server_name, required_secrets)
        input("\nPress Enter after you've configured the secrets...")
        print("✓ Continuing...\n")
        return True
    
    else:
        # Skip
        print("⚠️  Skipping secret configuration. Server may not work correctly.")
        proceed = input("Continue anyway? (y/n): ").strip().lower()
        return proceed == 'y'
    
def hil_configs(server: Dict):
    """
    Human-in-the-loop for config schema
    Returns (server_name, config_keys, config_values)
    """
    config_schema = server['config_schema'][0]
    print(f"\n--- Configuration Required ---")
    print(config_schema.get('description', 'No description'))

    config_server_name = config_schema['name']
    config_keys = list(config_schema['properties'].keys())
    required_keys = config_schema.get('required', [])

    print(f"\nRequired properties: {required_keys}")
    print(f"Optional properties: {[k for k in config_keys if k not in required_keys]}")

    config_values = []
    for key in config_keys:
        prop_info = config_schema['properties'][key]
        prop_desc = prop_info.get('description', '')
        prop_type = prop_info.get('type', 'string')
        is_required = key in required_keys

        prompt = f"\nEnter {key}"
        if prop_desc:
            prompt += f" ({prop_desc})"
        if is_required:
            prompt += " [REQUIRED]"
        prompt += ": "

        value = input(prompt).strip()

        # Validate required fields
        if is_required and not value:
            print(f"⚠️  '{key}' is required!")
            value = input(f"Enter {key} [REQUIRED]: ").strip()
        
        config_values.append(value)

    return config_server_name, config_keys, config_values