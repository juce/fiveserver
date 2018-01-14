create table if not exists settings (
    id bigint unsigned not null auto_increment,
    profile_id int unsigned not null,
    settings1 blob default null,
    settings2 blob default null,
    primary key(id),
    unique key(profile_id),
    foreign key(profile_id) references profiles (id)

) Engine=InnoDB default charset=utf8;

