"""Select the configured phone provider without credential fallback."""
from backend.safety.actions.elevenlabs import ElevenLabs, configured as elevenlabs_configured, trusted_message
from backend.safety.actions.sarvam import Sarvam, configured as sarvam_configured


def configured(config):
    return sarvam_configured(config) if config.SAFETY_CALL_PROVIDER == 'sarvam' else elevenlabs_configured(config)


def create_provider(config):
    return Sarvam(config) if config.SAFETY_CALL_PROVIDER == 'sarvam' else ElevenLabs(config)


def provider_label(config):
    return 'Sarvam hosted Voice Agents' if config.SAFETY_CALL_PROVIDER == 'sarvam' else 'ElevenLabs native Twilio'


def masked_recipient(config):
    number = config.SAFETY_ALERT_TO_NUMBER.get_secret_value()
    return f'•••• {number[-4:]}' if configured(config) else 'Not configured'
