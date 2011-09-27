// Copyright 2011 Facebook

$(function() {
    $("button.newrecipe").live("click", function() {
	location.href = "/edit";
	return false;
    });
    $("a.photoupload").live("click", function() {
	$("#uploaddialog input[name=recipe]").val($(this).attr("recipe"));
	$("#uploaddialog").fadeIn(150);
	return false;
    });
    // TODO: Loading indicators
    $("button.clip").live("click", function() {
	var button = $(this);
	button.attr("disabled", "disabled");
	$.post("/a/clip", {recipe: $(this).attr("recipe")},
	       function(response) {
	     $(".activity h3").after(response.html);
	     highlight($(".activity .action:first"));
	     button.get(0).className = "cook";
	     button.css({"opacity": 0});
	     window.setTimeout(function() {
		 button.removeAttr("disabled");
		 button.text("I just cooked this");
		 button.css({"opacity": 1});
	     }, 300);
	});
	return false;
    });
    $("button.cook").live("click", function() {
	var button = $(this);
	button.attr("disabled", "disabled");
	$.post("/a/cook", {recipe: $(this).attr("recipe")},
	       function(response) {
	     button.removeAttr("disabled");
	     $(".activity h3").after(response.html);
	     highlight($(".activity .action:first"));
	});
	return false;
    });
    $("button.dialogcancel").live("click", function() {
        $(this).parents("form").find("button").removeAttr("disabled");
	$(this).parents(".dialog").fadeOut(150).find(".loading").hide();
    });
    $("#uploaddialog form").live("submit", function() {
	$("#uploaddialog button[type=submit]").attr("disabled", "disabled");
	$("#uploaddialog .loading").show();
        return true;
    });
    $("#uploaddialog input[type=file]").live("change", function() {
	$(this).parents("form").submit();
    });
    $("a.newcategory").live("click", function() {
	var div = $(this).parent();
	var current = div.find("select").val();
	div.html('<input name="category">').find("input").val(current).select();
	return false;
    });
    $("form.edit").live("submit", function() {
	var required = ["title", "description", "category"];
	for (var i = 0; i < required.length; i++) {
	    if (!this[required[i]].value) {
		this[required[i]].select();
		return false;
	    }
	}
	return true;
    });
    window.setTimeout(function() {
	$("#error").slideUp();
    }, 4000);
});


function highlight(node) {
    node.addClass("highlighted");
    node.hide();
    node.slideDown();
    window.setTimeout(function() {
	node.removeClass("highlighted");
    }, 1500);
}
