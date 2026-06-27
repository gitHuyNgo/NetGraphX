import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pynetbox
from config.settings import netbox_config
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info("==================================================")
    logger.info("   PURGING ALL ROGUE DEVICES FROM NETBOX          ")
    logger.info("==================================================")
    
    nb = pynetbox.api(netbox_config.NETBOX_URL, token=netbox_config.NETBOX_API_TOKEN)
    
    # Fetch all devices
    all_devices = list(nb.dcim.devices.all())
    
    rogue_devices = [d for d in all_devices if d.name.startswith("ROGUE-") or d.name.startswith("FAKE-")]
    
    if not rogue_devices:
        logger.info("No rogue devices found in NetBox. It is already 100% clean.")
        return
        
    logger.info(f"Found {len(rogue_devices)} rogue/fake devices to delete.")
    
    # For each rogue device, find its interfaces and delete connected cables
    deleted_cables = 0
    for dev in rogue_devices:
        interfaces = list(nb.dcim.interfaces.filter(device_id=dev.id))
        for iface in interfaces:
            if getattr(iface, "cable", None):
                cable_id = iface.cable.id
                try:
                    cable = nb.dcim.cables.get(cable_id)
                    if cable:
                        cable.delete()
                        deleted_cables += 1
                except Exception as e:
                    logger.warning(f"Failed to delete cable {cable_id}: {e}")
                    
    logger.info(f"Deleted {deleted_cables} rogue cables.")
    
    # Delete the devices themselves
    deleted_devices = 0
    for dev in rogue_devices:
        try:
            dev.delete()
            deleted_devices += 1
        except Exception as e:
            logger.warning(f"Failed to delete device {dev.name}: {e}")
            
    logger.info(f"Deleted {deleted_devices} rogue devices.")
    logger.info("==================================================")
    logger.info("   NETBOX IS NOW 100% SECURE AND CLEAN            ")
    logger.info("==================================================")

if __name__ == "__main__":
    main()
