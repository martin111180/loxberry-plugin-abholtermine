#!/bin/bash
# Läuft als loxberry nach einem Update: gesicherte Konfiguration zurückspielen.
# (postinstall.sh lief bereits mit der Standardkonfiguration; Bridge danach neu starten)
PFOLDER=$3
LBHOMEDIR=$5
BACKUP=/tmp/${1##*/}_upgrade
PCONFIG=$LBHOMEDIR/config/plugins/$PFOLDER

if [ -f "$BACKUP/config/abholtermine.json" ]; then
	cp -p -v "$BACKUP/config/abholtermine.json" "$PCONFIG/abholtermine.json"
	chmod 600 "$PCONFIG/abholtermine.json"
	echo "<OK> Konfiguration wiederhergestellt"
fi
rm -rf "$BACKUP"

"$LBHOMEDIR/bin/plugins/$PFOLDER/service.sh" restart
exit 0
