wget -O skynet.list https://raw.githubusercontent.com/Adamm00/IPSet_ASUS/refs/heads/master/filter.list \
&& paste -s -d "\n" skynet.list custom.list > filter.list \
&& git add . \
&& git commit -m "Update list" \
&& git push 
