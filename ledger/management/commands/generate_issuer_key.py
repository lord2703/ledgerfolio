from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chain_node.wallet import Wallet

DEFAULT_PATH = Path.home() / ".ledgerfolio" / "issuer_key.pem"


class Command(BaseCommand):
    help = (
        "Create the issuer wallet: the secp256k1 private key that signs receipts. "
        "The key is written to a file outside the repository and never printed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--path", default=str(DEFAULT_PATH), help=f"Where to save the key (default: {DEFAULT_PATH})"
        )
        parser.add_argument(
            "--force", action="store_true", help="Overwrite an existing key file (old receipts "
            "will no longer verify as signed by the issuer)"
        )

    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser().resolve()
        if settings.BASE_DIR.resolve() in path.parents:
            raise CommandError("Keep the key outside the project folder so it can never be committed.")
        if path.exists() and not options["force"]:
            raise CommandError(
                f"{path} already exists. Receipts already issued are signed with it, so it is "
                "not overwritten. Use --path for a different file, or --force if you are sure."
            )

        wallet = Wallet.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wallet.to_pem())
        try:
            path.chmod(0o600)
        except OSError:
            pass

        self.stdout.write(self.style.SUCCESS(f"Issuer key saved to {path}"))
        self.stdout.write(f"Public key: {wallet.public_key_hex}")
        self.stdout.write(f"Address:    {wallet.address}")
        self.stdout.write("")
        self.stdout.write("Next steps:")
        self.stdout.write(f"  1. Put this line in .env:  ISSUER_KEY_FILE={path}")
        self.stdout.write("  2. Back the file up somewhere safe. If it is lost, new receipts cannot")
        self.stdout.write("     be signed as you; if it leaks, someone else can sign as you.")
