wget https://raw.githubusercontent.com/Adamm00/IPSet_ASUS/refs/heads/master/filter.list \
&& echo "\nhttps://iplists.firehol.org/files/firehol_abusers_1d.netset" >> filter.list \
&& git add . \
&& git commit -m "Update list" \
&& git push
