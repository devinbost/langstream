package com.datastax.oss.sga.api.runner.code;

import java.util.Collection;
public interface Record {
    Object key();
    Object value();
    String origin();
    Long timestamp();
    Collection<Header> headers();
}