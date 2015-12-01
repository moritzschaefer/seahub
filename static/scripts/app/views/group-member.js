define([
    'jquery',
    'underscore',
    'backbone',
    'common'
], function($, _, Backbone, Common) {
    'use strict';

    var GroupMemberView = Backbone.View.extend({
        tagName: 'li',

        template: _.template($('#group-member-tmpl').html()),

        initialize: function() {
            this.$group_member_avatar = this.model.get('avatar');
            this.$group_member_email = this.model.get('username');
            this.$group_member_fullname = this.model.get('fullname');
        },

        render: function() {
            var obj = {
                group_member_avatar: this.$group_member_avatar,
                group_member_email: this.$group_member_email,
                group_member_fullname: this.$group_member_fullname
            }
            this.$el.html(this.template(obj));
            return this;
        },

        events: {
            'mouseenter': 'highlight',
            'mouseleave': 'rmHighlight'
        },

        highlight: function() {
            this.$el.addClass('hl');
        },

        rmHighlight: function() {
            this.$el.removeClass('hl');
        }

    });

    return GroupMemberView;
});
