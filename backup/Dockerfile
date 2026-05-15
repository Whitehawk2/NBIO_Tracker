FROM alpine:3.20

RUN apk add --no-cache sqlite rclone tzdata bash gzip coreutils

COPY backup.sh restore.sh /usr/local/bin/
COPY crontab /etc/crontabs/root
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh \
 && mkdir -p /backups /config /data /var/log

VOLUME ["/data", "/backups", "/config"]

CMD ["crond", "-f", "-l", "8"]
